# KARMA web.
#
# Referenced by ../docker-compose.yml as `build: ./frontend`. Like the backend image this did
# not exist, so `docker compose up --build` could not run.
#
# Two stages: Node builds the bundle, nginx serves it. The nginx stage is not optional -- the
# app calls `/api/v1` on its own origin (see src/api/client.ts), and the real-time socket
# derives its URL from `window.location.host` (see src/api/realtime.ts). Serving the bundle
# without a proxy on /api would mean the API host has to be baked into the JavaScript, which
# is exactly the CORS-and-exposed-host arrangement the same-origin design exists to avoid.
FROM node:22-alpine AS build

WORKDIR /app

# package-lock.json is copied with package.json so `npm ci` can verify the tree; copying the
# source afterwards keeps that layer cached across code edits.
COPY package.json package-lock.json ./
RUN npm ci

COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src

# `npm run build` is `tsc -b && vite build`, so a type error fails the image build rather than
# shipping a bundle that only breaks in the browser.
RUN npm run build


FROM nginx:1.27-alpine

# The reverse proxy that makes same-origin true in production.
COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html

# Unprivileged nginx: the stock image listens on 80 as root. This config listens on 8080 so
# the container needs no capability to bind a low port.
RUN chown -R nginx:nginx /usr/share/nginx/html \
    && chown -R nginx:nginx /var/cache/nginx \
    && chown -R nginx:nginx /var/log/nginx \
    && touch /var/run/nginx.pid \
    && chown nginx:nginx /var/run/nginx.pid

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
