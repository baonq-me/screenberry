# Generate

```
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout selfsigned.key -out selfsigned.crt \
  -subj "/CN=screenberry-s3.baonq.me" \
  -addext "subjectAltName=DNS:screenberry-s3.baonq.me"
```