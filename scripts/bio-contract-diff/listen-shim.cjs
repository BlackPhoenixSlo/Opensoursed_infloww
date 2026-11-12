// node -r ./listen-shim.cjs server.js: ofl.ink v2's server.js listens on a hard-coded 3000 on every interface; this moves
// that one listen to $PORT on 127.0.0.1 (loopback only), so the diff run needs neither port 3000 nor a public bind.
'use strict';
const net = require('net');

const listen = net.Server.prototype.listen;
net.Server.prototype.listen = function (...args) {
  if (args[0] === 3000 && process.env.PORT) {
    args[0] = Number(process.env.PORT);
    if (typeof args[1] === 'function') args.splice(1, 0, '127.0.0.1');
    else args[1] = '127.0.0.1';
  }
  return listen.apply(this, args);
};
