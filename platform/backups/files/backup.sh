#!/bin/sh
set -eu
kubectl=/tools/kubectl
export RESTIC_REPOSITORY="s3:${BACKUP_ENDPOINT}/${BACKUP_BUCKET}/files/${POD_NAMESPACE}"
resume_state="$($kubectl get deployment "$DEPLOYMENT" -o jsonpath='{.metadata.annotations.backup\.excloo\.dev/resume-state}')"
if [ -n "$resume_state" ]; then
  replicas="${resume_state%/*}"
  suspended="${resume_state#*/}"
else
  replicas="$($kubectl get deployment "$DEPLOYMENT" -o jsonpath='{.spec.replicas}')"
  suspended="$($kubectl get helmrelease "$HELM_RELEASE" -o jsonpath='{.spec.suspend}')"
  suspended="${suspended:-false}"
fi
case "$replicas" in
  '' | *[!0-9]*) echo "Invalid backup replica recovery state" >&2; exit 1 ;;
esac
case "$suspended" in
  true | false) ;;
  *) echo "Invalid backup suspension recovery state" >&2; exit 1 ;;
esac
# shellcheck disable=SC2016
selector="$($kubectl get deployment "$DEPLOYMENT" -o go-template='{{range $key,$value := .spec.selector.matchLabels}}{{$key}}={{$value}},{{end}}')"
selector="${selector%,}"
resume() {
  $kubectl scale deployment "$DEPLOYMENT" --replicas="$replicas" || return
  $kubectl patch helmrelease "$HELM_RELEASE" --type merge -p "{\"spec\":{\"suspend\":$suspended}}" || return
  $kubectl annotate deployment "$DEPLOYMENT" backup.excloo.dev/resume-state-
}
# Persist intent before quiescing; SIGKILL and pod loss cannot run the exit trap.
if [ -z "$resume_state" ]; then
  $kubectl annotate deployment "$DEPLOYMENT" "backup.excloo.dev/resume-state=$replicas/$suspended"
fi
trap resume EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
$kubectl patch helmrelease "$HELM_RELEASE" --type merge -p '{"spec":{"suspend":true}}'
# Terminated pods, such as those stopped by node shutdown, are never deleted on scale-down.
pods="$($kubectl get pods -l "$selector" --field-selector=status.phase!=Failed,status.phase!=Succeeded -o name)"
$kubectl scale deployment "$DEPLOYMENT" --replicas=0
if [ -n "$pods" ]; then
  # Each token is a kubectl pod resource name, never shell input.
  # shellcheck disable=SC2086
  $kubectl wait --for=delete $pods --timeout=120s
fi
cp -R /sources/. /snapshot/data/
resume
trap - EXIT INT TERM
restic cat config >/dev/null 2>&1 || restic init
restic backup --host "syd/${POD_NAMESPACE}" --tag app-state /snapshot
restic forget --keep-within 14d --prune
