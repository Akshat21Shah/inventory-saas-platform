# Web (Next.js). Build context: web/
FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS dev
COPY . .
EXPOSE 3000
# server.mjs: Next.js behind our own forwarded-header handling (ADR-032). Binds 0.0.0.0:3000.
CMD ["npm", "run", "dev"]

FROM deps AS build
COPY . .
RUN npm run build

FROM node:24-alpine AS prod
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build /app/package.json /app/package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/messages ./messages
COPY --from=build /app/next.config.ts ./next.config.ts
COPY --from=build /app/server.mjs ./server.mjs
COPY --from=build /app/server ./server
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
