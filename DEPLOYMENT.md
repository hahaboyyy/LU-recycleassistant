# Publish and verify live recognition

The local application and the public service are separate deployments. Publishing
code alone does not change an existing Render service's environment variables.

`render.yaml` provides an optional free-plan Blueprint for a new service. It does
not contain a credential and has not been applied to the existing service by this
repair. In the existing service, set or verify these values:

```text
PYTHONPATH=recognition/src
RECYCLE_D_BACKEND=integration:create_live_backend
RECYCLE_D_TIMEOUT=35
RECO_PROVIDER=deepseek
RECO_BASE_URL=https://api.deepseek.com/v1
RECO_MODEL=deepseek-v4-flash-vision-exp
RECO_MAX_TOKENS=4096
RECO_MAX_RETRIES=1
RECO_TIMEOUT=15
RECO_API_KEY=<set privately in the service environment>
```

Start command:

```sh
python -m streamlit run app.py --server.address 0.0.0.0 --server.port "$PORT" --server.headless true
```

The model request name is the legacy alias used in the measured runs. Current
provider documentation routes it to the Flash service. Retain the request and
returned model labels in experiment records; a request alias does not identify
backend weights independently.

After redeploying, verify that the page no longer shows `Demo mode`, then upload
at least two different fresh photos. Confirm that the object and advice change
with the photos. Also exercise a correction, a clarification when triggered, and
the retry path. A local API batch is not evidence that the public service passed
these checks. Do not send credentials in screenshots or group messages.
