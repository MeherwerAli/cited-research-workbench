FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000
RUN addgroup -S workbench && adduser -S workbench -G workbench
WORKDIR /app
COPY --from=build --chown=workbench:workbench /app/.next/standalone ./
COPY --from=build --chown=workbench:workbench /app/.next/static ./.next/static
USER workbench
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD ["wget", "--spider", "-q", "http://127.0.0.1:3000/"]
CMD ["node", "server.js"]
