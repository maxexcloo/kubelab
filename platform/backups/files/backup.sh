#!/bin/sh
set -eu
: "${CLUSTER:?CLUSTER is required}"
# Bound calls with timeout: any kubectl client flag disables in-cluster configuration.
kubectl() { timeout 180 /tools/kubectl "$@"; }
export RESTIC_REPOSITORY="s3:${BACKUP_ENDPOINT}/${BACKUP_BUCKET}/files/${POD_NAMESPACE}"
validate_resume_state() {
  case "${1%/*}" in
    '' | *[!0-9]*) echo "Invalid backup replica recovery state" >&2; return 1 ;;
  esac
  case "${1#*/}" in
    true | false) ;;
    *) echo "Invalid backup suspension recovery state" >&2; return 1 ;;
  esac
}
resume() {
  kubectl scale deployment "$DEPLOYMENT" --replicas="${1%/*}" || return
  kubectl patch helmrelease "$HELM_RELEASE" --type merge -p "{\"spec\":{\"suspend\":${1#*/}}}" || return
  kubectl annotate deployment "$DEPLOYMENT" backup.excloo.dev/resume-state-
}
previous_state="$(kubectl get deployment "$DEPLOYMENT" -o jsonpath='{.metadata.annotations.backup\.excloo\.dev/resume-state}')"
if [ -n "$previous_state" ]; then
  validate_resume_state "$previous_state"
  resume "$previous_state"
fi
replicas="$(kubectl get deployment "$DEPLOYMENT" -o jsonpath='{.spec.replicas}')"
suspended="$(kubectl get helmrelease "$HELM_RELEASE" -o jsonpath='{.spec.suspend}')"
resume_state="$replicas/${suspended:-false}"
validate_resume_state "$resume_state"
# shellcheck disable=SC2016
selector="$(kubectl get deployment "$DEPLOYMENT" -o go-template='{{range $key,$value := .spec.selector.matchLabels}}{{$key}}={{$value}},{{end}}')"
selector="${selector%,}"
# Persist intent before quiescing; SIGKILL and pod loss cannot run the exit trap.
kubectl annotate deployment "$DEPLOYMENT" "backup.excloo.dev/resume-state=$resume_state"
trap 'resume "$resume_state"' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
kubectl patch helmrelease "$HELM_RELEASE" --type merge -p '{"spec":{"suspend":true}}'
# Terminated pods, such as those stopped by node shutdown, are never deleted on scale-down.
pods="$(kubectl get pods -l "$selector" --field-selector=status.phase!=Failed,status.phase!=Succeeded -o name)"
kubectl scale deployment "$DEPLOYMENT" --replicas=0
if [ -n "$pods" ]; then
  # Each token is a kubectl pod resource name, never shell input.
  # shellcheck disable=SC2086
  kubectl wait --for=delete $pods --timeout=120s
fi
if [ -f /hooks/snapshot.sh ]; then
  /bin/sh /hooks/snapshot.sh
fi
timeout 600 cp -R /sources/. /snapshot/data/
resume "$resume_state"
trap - EXIT INT TERM
restic cat config >/dev/null 2>&1 || restic init
restic backup --host "${CLUSTER}/${POD_NAMESPACE}" --tag app-state /snapshot
restic forget --keep-within 14d --prune
