{{- define "aidlc.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "aidlc.fullname" -}}
{{- default .Release.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "aidlc.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "aidlc.selectorLabels" -}}
app.kubernetes.io/name: {{ include "aidlc.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "aidlc.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{ .Values.secrets.existingSecret }}
{{- else -}}
{{ include "aidlc.fullname" . }}-secrets
{{- end -}}
{{- end -}}
