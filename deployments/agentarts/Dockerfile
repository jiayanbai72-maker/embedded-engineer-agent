# Build on an ARM64 builder, or explicitly enable linux/arm64 emulation.
FROM python:3.11-slim
WORKDIR /opt/embedded-agent
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/embedded-agent/src CLOUD_PORT=8080 CLOUD_TRUST_GATEWAY=1
COPY src ./src
COPY deployments ./deployments
COPY knowledge ./knowledge
COPY docs ./docs
EXPOSE 8080
# No model credentials or personal runtime data are copied into the image.
CMD ["python", "-m", "deployments.agentarts.app"]
