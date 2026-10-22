# Base image from ECR Public: avoids Docker Hub pull limits inside CodeBuild.
# For production, pin by digest as well: node:22-alpine@sha256:...
FROM public.ecr.aws/docker/library/node:22-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY server.js ./
USER node
EXPOSE 8080
CMD ["node", "server.js"]
