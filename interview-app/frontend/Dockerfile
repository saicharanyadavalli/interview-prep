# syntax=docker/dockerfile:1

# ============================================
# Next.js Production Dockerfile (Node.js 20/22 Alpine)
# Optimized Multi-Stage Build
# ============================================

# --- Stage 1: Dependencies ---
FROM node:20-alpine AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# --- Stage 2: Builder ---
FROM node:20-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Pass build-time public environment variables if needed
ARG NEXT_PUBLIC_API_BASE_URL
ARG COGNITO_REGION
ARG COGNITO_USER_POOL_ID
ARG COGNITO_CLIENT_ID
ARG COGNITO_DOMAIN
ARG PUBLIC_APP_ORIGIN
ARG AUTH_REDIRECT_URL
ARG NEXT_PUBLIC_AUTH_REDIRECT_URL
ARG FRONTEND_URL
ARG NEXT_PUBLIC_APP_URL

ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL:-/api/backend}
ENV COGNITO_REGION=${COGNITO_REGION:-ap-south-2}
ENV COGNITO_USER_POOL_ID=${COGNITO_USER_POOL_ID}
ENV COGNITO_CLIENT_ID=${COGNITO_CLIENT_ID}
ENV COGNITO_DOMAIN=${COGNITO_DOMAIN}
ENV PUBLIC_APP_ORIGIN=${PUBLIC_APP_ORIGIN:-https://app.interviewprep.com}
ENV AUTH_REDIRECT_URL=${AUTH_REDIRECT_URL:-https://app.interviewprep.com/auth/callback?next=/dashboard}
ENV NEXT_PUBLIC_AUTH_REDIRECT_URL=${NEXT_PUBLIC_AUTH_REDIRECT_URL:-${AUTH_REDIRECT_URL:-https://app.interviewprep.com/auth/callback?next=/dashboard}}
ENV FRONTEND_URL=${FRONTEND_URL:-https://app.interviewprep.com}
ENV NEXT_PUBLIC_APP_URL=${NEXT_PUBLIC_APP_URL:-${FRONTEND_URL:-https://app.interviewprep.com}}
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

RUN npm run build

# --- Stage 3: Runner ---
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"
ENV COGNITO_REGION=${COGNITO_REGION:-ap-south-2}
ENV COGNITO_USER_POOL_ID=${COGNITO_USER_POOL_ID}
ENV COGNITO_CLIENT_ID=${COGNITO_CLIENT_ID}
ENV COGNITO_DOMAIN=${COGNITO_DOMAIN}
ENV PUBLIC_APP_ORIGIN=${PUBLIC_APP_ORIGIN:-https://app.interviewprep.com}
ENV AUTH_REDIRECT_URL=${AUTH_REDIRECT_URL:-https://app.interviewprep.com/auth/callback?next=/dashboard}
ENV FRONTEND_URL=${FRONTEND_URL:-https://app.interviewprep.com}
ENV NEXT_PUBLIC_AUTH_REDIRECT_URL=${NEXT_PUBLIC_AUTH_REDIRECT_URL:-https://app.interviewprep.com/auth/callback?next=/dashboard}
ENV NEXT_PUBLIC_APP_URL=${NEXT_PUBLIC_APP_URL:-https://app.interviewprep.com}

# Non-root security user
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy static assets and built application
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next ./.next
COPY --from=builder --chown=nextjs:nodejs /app/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nodejs /app/package.json ./package.json

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1

CMD ["npm", "run", "start"]
