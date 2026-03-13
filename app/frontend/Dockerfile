# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first (for layer caching)
COPY package*.json ./
RUN npm ci --prefer-offline --no-audit

# Copy source and build
COPY . .

# Set production environment for optimizations
ENV NODE_ENV=production

# Build with optimizations
RUN npm run build

# ── Stage 2: serve via nginx ──────────────────────────────────────────────────
FROM nginx:1.25-alpine

# Copy built files
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/health || exit 1

# Create health check endpoint by ensuring index.html exists
RUN echo "OK" > /usr/share/nginx/html/health

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
