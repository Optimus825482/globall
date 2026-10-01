FROM node:20-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_VAPID_PUBLIC_KEY=""
# 2026-09-26 (Binance Global): `NEXT_PUBLIC_*` Next.js tarafından BUILD
# anında sabitlenir, çalışma anında okunmaz. Bu yüzden TR (TRY/₺) ve Global
# (USDT) örnekleri AYRI imaj/derleme gerektirir — `docker-compose.yaml`'daki
# `frontend` ve `frontend_global` bu ARG'ı farklı değerlerle geçer.
ARG NEXT_PUBLIC_QUOTE_ASSET="USDT"
ENV NEXT_PUBLIC_API_URL=
ENV NEXT_PUBLIC_WS_URL=
ENV NEXT_PUBLIC_VAPID_PUBLIC_KEY=${NEXT_PUBLIC_VAPID_PUBLIC_KEY}
ENV NEXT_PUBLIC_QUOTE_ASSET=${NEXT_PUBLIC_QUOTE_ASSET}
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production PORT=3005
# Next.js yalnızca $HOSTNAME değerine bağlanıyor; varsayılanda container
# hostname'i kullanıyor → 127.0.0.1/localhost'ta dinlemiyor → healthcheck
# "Connection refused" ile unhealthy düşüyor (gateway timeout + route düşmesi).
# 0.0.0.0 ile tüm arayüzlere (localhost dahil) bağlanır.
ENV HOSTNAME=0.0.0.0
COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3005
CMD ["node", "server.js"]
