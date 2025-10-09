# Migration to Ingress with Let's Encrypt - Implementation Summary

## ✅ Changes Completed

### 1. Created Let's Encrypt ClusterIssuer
- **File**: `letsencrypt-issuer.yaml`
- Contains both staging and production issuers
- **IMPORTANT**: Update the email address in this file before deploying!
  - Replace `your-email@example.com` with your actual email (line 9 and line 23)

### 2. Updated Grafana (`grafana.yaml`)
- ✅ Changed Service from `NodePort` to `ClusterIP`
- ✅ Removed `nodePort: 30090`
- ✅ Added Ingress resource with Let's Encrypt certificate
- ✅ Updated Prometheus datasource URL to use internal Kubernetes DNS: `http://prometheus.monitoring.svc.cluster.local`
- ✅ Configured for domain: `grafana.server.robertgogete.eu`

### 3. Updated Prometheus (`prometheus.yaml`)
- ✅ Changed Service from `NodePort` to `ClusterIP`
- ✅ Removed `nodePort: 30091`
- ✅ Added Ingress resource with Let's Encrypt certificate
- ✅ Configured for domain: `prometheus.server.robertgogete.eu`

### 4. Deleted Old Certificate Files
- ✅ Removed `grafana-selfsigned-issuer.yaml`
- ✅ Removed `registry-selfsigned-issuer.yaml`
- ✅ Removed `ca-issuer.yml`

## 📋 Pre-Deployment Checklist

### 1. Update Email in letsencrypt-issuer.yaml
```yaml
email: your-email@example.com  # <- Change this to your real email
```

### 2. Verify DNS Configuration
Ensure these DNS records point to your server's PUBLIC IP address:
- `grafana.server.robertgogete.eu` → Your server's public IP
- `prometheus.server.robertgogete.eu` → Your server's public IP

Note: The local hosts file (192.168.1.186) is only for testing from your PC. For Let's Encrypt to work, these domains must resolve to your public IP from the internet.

### 3. Configure Firewall/Port Forwarding
Ensure ports are accessible from the internet:
- **Port 80 (HTTP)**: Required for Let's Encrypt ACME HTTP-01 challenge
- **Port 443 (HTTPS)**: Required for accessing services via HTTPS

### 4. Verify Traefik is Running
K3s comes with Traefik by default. Verify it's running:
```bash
kubectl get pods -n kube-system | grep traefik
```

## 🚀 Deployment Steps

### Option 1: Test with Staging First (Recommended)
1. Edit both `grafana.yaml` and `prometheus.yaml`
2. Change annotation from:
   ```yaml
   cert-manager.io/cluster-issuer: letsencrypt-prod
   ```
   to:
   ```yaml
   cert-manager.io/cluster-issuer: letsencrypt-staging
   ```

3. Deploy using Ansible:
   ```bash
   ansible-playbook -i inventory deploy-manifests.yml
   ```

4. Verify certificates are issued (on server):
   ```bash
   kubectl get certificate -n monitoring
   kubectl describe certificate grafana-tls -n monitoring
   kubectl describe certificate prometheus-tls -n monitoring
   ```

5. Test access (you'll see certificate warnings with staging):
   - https://grafana.server.robertgogete.eu
   - https://prometheus.server.robertgogete.eu

6. If everything works, change back to `letsencrypt-prod` and redeploy

### Option 2: Deploy Directly to Production
1. Update email in `letsencrypt-issuer.yaml`
2. Deploy using Ansible:
   ```bash
   ansible-playbook -i inventory deploy-manifests.yml
   ```

3. Monitor certificate issuance (on server):
   ```bash
   kubectl get certificate -n monitoring
   kubectl describe certificate grafana-tls -n monitoring
   kubectl describe certificate prometheus-tls -n monitoring
   ```

## 🔍 Troubleshooting

### Certificate Not Issued
```bash
# Check certificate status
kubectl get certificate -n monitoring

# Check certificate request
kubectl get certificaterequest -n monitoring

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager

# Check ingress
kubectl get ingress -n monitoring
kubectl describe ingress grafana -n monitoring
```

### Can't Access Services
1. Verify Ingress is created:
   ```bash
   kubectl get ingress -n monitoring
   ```

2. Check Traefik routes:
   ```bash
   kubectl get ingressroute -A
   ```

3. Verify services are running:
   ```bash
   kubectl get pods -n monitoring
   kubectl get svc -n monitoring
   ```

### Let's Encrypt Rate Limits
- Staging: No rate limits (use for testing)
- Production: 50 certificates per domain per week
- If you hit rate limits, use staging issuer until configuration is stable

## 📝 Next Steps (After Grafana & Prometheus)

Once Grafana and Prometheus are working, you can migrate other services:
- Registry
- Keycloak
- Nostalgia Service
- Minecraft (note: Minecraft uses TCP, not HTTP, so Ingress won't work - keep as NodePort)

## 🔒 Security Considerations

1. **Basic Auth**: Consider adding basic auth to Prometheus:
   ```yaml
   annotations:
     traefik.ingress.kubernetes.io/router.middlewares: monitoring-auth@kubernetescrd
   ```

2. **Keycloak Integration**: Grafana can use Keycloak for authentication

3. **Network Policies**: Consider restricting access between namespaces

## 📚 Additional Resources

- [cert-manager documentation](https://cert-manager.io/docs/)
- [Traefik Ingress documentation](https://doc.traefik.io/traefik/providers/kubernetes-ingress/)
- [Let's Encrypt documentation](https://letsencrypt.org/docs/)
