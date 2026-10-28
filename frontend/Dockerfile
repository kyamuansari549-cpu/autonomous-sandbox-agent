# Frontend image for the autonomous sandbox agent (Milestone 9).
#
# Builds the React app with Vite and serves the static bundle with
# `vite preview`. VITE_API_BASE_URL is a BUILD-TIME value: Vite bakes
# it into the bundle, so it is passed as a build argument (compose
# supplies it); changing it later requires a rebuild. The default in
# src/api.ts (http://localhost:8000) matches the compose port mapping,
# because the browser — not this container — calls the backend.
FROM node:22-alpine

WORKDIR /app

# Dependencies first for layer caching; the lockfile makes this exact.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

EXPOSE 5173

CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "5173"]
