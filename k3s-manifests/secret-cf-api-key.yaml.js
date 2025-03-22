apiVersion: v1
kind: Secret
metadata:
  name: cf-api-key
type: Opaque
data:
  CF_API_KEY: "{{ CF_API_KEY | b64encode }}"
