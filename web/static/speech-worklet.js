class GatorPcmTap extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buf = new Float32Array(1024);
    this._len = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this._buf[this._len++] = ch[i];
      if (this._len === this._buf.length) {
        this.port.postMessage(this._buf.slice(0));
        this._len = 0;
      }
    }
    return true;
  }
}

registerProcessor('gator-pcm-tap', GatorPcmTap);
