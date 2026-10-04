// Entry point: listen on 0.0.0.0:$PORT (default 8080).

import { createApp } from './app.ts';

const port = Number.parseInt(process.env.PORT ?? '', 10);
const server = createApp();
server.listen(Number.isInteger(port) && port > 0 && port < 65536 ? port : 8080, '0.0.0.0', () => {
  const address = server.address();
  console.log(`pocketful listening on ${typeof address === 'object' && address ? address.port : address}`);
});

for (const signal of ['SIGTERM', 'SIGINT'] as const) {
  process.on(signal, () => process.exit(0));
}
