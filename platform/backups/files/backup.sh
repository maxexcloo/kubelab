#!/bin/sh
set -eu
kubectl=/tools/kubectl
export RESTIC_REPOSITORY="s3:${BACKUP_ENDPOINT}/${BACKUP_BUCKET}/files/${POD_NAMESPACE}"
replicas="$($kubectl get deployment "$DEPLOYMENT" -o jsonpath='{.spec.replicas}')"
suspended="$($kubectl get helmrelease "$HELM_RELEASE" -o jsonpath='{.spec.suspend}')"
# shellcheck disable=SC2016
selector="$($kubectl get deployment "$DEPLOYMENT" -o go-template='{{range $key,$value := .spec.selector.matchLabels}}{{$key}}={{$value}},{{end}}')"
selector="${selector%,}"
resume() {
  $kubectl scale deployment "$DEPLOYMENT" --replicas="$replicas"
  $kubectl patch helmrelease "$HELM_RELEASE" --type merge -p "{\"spec\":{\"suspend\":${suspended:-false}}}"
}
trap resume EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
$kubectl patch helmrelease "$HELM_RELEASE" --type merge -p '{"spec":{"suspend":true}}'
pods="$($kubectl get pods -l "$selector" -o name)"
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
