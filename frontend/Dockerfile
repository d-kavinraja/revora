FROM node:18-alpine

WORKDIR /app

# Install dependencies based on the preferred package manager
COPY package.json package-lock.json* ./
RUN npm ci

# Copy application code
COPY . .

# Build Next.js production bundle, then serve it (was: dev server).
RUN npm run build

# Next.js telemetry disable
ENV NEXT_TELEMETRY_DISABLED 1
ENV NODE_ENV production

CMD ["npm", "run", "start"]
