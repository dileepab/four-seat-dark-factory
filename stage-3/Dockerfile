# Pocketful stage 3. The build downloads nothing: it copies the source and the UI files onto a
# pinned Node 24 image, which runs the TypeScript through Node's built-in type stripping.
FROM node:24.14.0-alpine3.22

ENV NODE_ENV=production \
    PORT=8080

WORKDIR /app
COPY package.json ./
COPY src ./src
COPY ui ./ui

USER node
EXPOSE 8080
CMD ["node", "src/main.ts"]
