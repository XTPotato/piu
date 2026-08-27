/* piu Web Audio bridge.
 *
 * Inlined into the page by tools/make_template.py and driven from
 * piu/core/clock.py.
 *
 * Why a JS bridge rather than calling Web Audio directly from Python:
 * decodeAudioData and AudioContext.resume() are promise-based, and awaiting a
 * JS promise from pygbag's Python is the least dependable part of the interop.
 * Everything asynchronous is therefore kept on this side, and Python only ever
 * reads a status string and a number. Nothing here can leave Python blocked on
 * a promise that never bridges.
 *
 * The clock itself is AudioContext.currentTime. It is driven by the same
 * hardware clock as the audio output, it is monotonic, and it does not drift
 * against what the player actually hears - which is exactly the property a
 * rhythm game needs and the reason this replaced the native sounddevice
 * design when the project moved to the browser.
 */
(function () {
  "use strict";

  function log(kind, message) {
    if (window.piuBootLog) window.piuBootLog(kind, message);
  }

  var piuAudio = {
    ctx: null,
    buffer: null,
    source: null,

    // idle -> loading -> ready -> playing -> stopped, or error at any point.
    status: "idle",
    error: "",

    // Context time at which playback position 0 occurs, and the offset into
    // the buffer that playback started from.
    t0: 0,
    startOffset: 0,
    pausedAt: null,

    /* Create the AudioContext. Must be called after a user gesture; browsers
     * refuse otherwise, and Safari is strictest. Returns true on success. */
    init: function () {
      if (this.ctx) return true;
      try {
        var Ctor = window.AudioContext || window.webkitAudioContext;
        if (!Ctor) {
          this.status = "error";
          this.error = "Web Audio API is unavailable in this browser";
          log("FAIL", "audio: " + this.error);
          return false;
        }
        this.ctx = new Ctor();
        log("OK", "audio: context created, sampleRate=" + this.ctx.sampleRate +
          "Hz, baseLatency=" + this.describeLatency());
        // A context created before the gesture lands in "suspended".
        if (this.ctx.state === "suspended") {
          this.ctx.resume().then(
            function () { log("OK", "audio: context resumed"); },
            function (e) { log("WARN", "audio: resume rejected: " + e); }
          );
        }
        return true;
      } catch (e) {
        this.status = "error";
        this.error = String(e);
        log("FAIL", "audio: could not create context: " + e);
        return false;
      }
    },

    describeLatency: function () {
      if (!this.ctx) return "n/a";
      var base = this.ctx.baseLatency;
      var out = this.ctx.outputLatency;
      return (
        (base === undefined ? "?" : (base * 1000).toFixed(1) + "ms") +
        " base, " +
        (out === undefined ? "unreported" : (out * 1000).toFixed(1) + "ms") +
        " output"
      );
    },

    /* Total output latency in seconds: how far ahead of the speaker the
     * context clock runs. Subtracted from the reported position so that
     * position() means "what the player is hearing right now".
     *
     * Browsers report this inconsistently and some omit outputLatency
     * entirely, which is why calibration still exists. */
    latency: function () {
      if (!this.ctx) return 0;
      var out = this.ctx.outputLatency;
      if (typeof out === "number" && isFinite(out) && out > 0) return out;
      var base = this.ctx.baseLatency;
      if (typeof base === "number" && isFinite(base) && base > 0) return base;
      return 0;
    },

    /* Build a click track directly, with no asset and no network.
     *
     * Clicks land on exact sample indices computed from the beat period, so
     * the reference the timing rig measures against is arithmetic rather than
     * something decoded from a file. Any offset measured is therefore the
     * pipeline's, not the material's. */
    makeClickTrack: function (bpm, beats, leadIn, accentEvery) {
      if (!this.init()) return false;
      try {
        var sr = this.ctx.sampleRate;
        var period = 60.0 / bpm;
        var tail = 0.5;
        var length = Math.ceil((leadIn + beats * period + tail) * sr);
        var buffer = this.ctx.createBuffer(1, length, sr);
        var data = buffer.getChannelData(0);

        var clickSeconds = 0.012;
        var clickSamples = Math.floor(clickSeconds * sr);

        for (var b = 0; b < beats; b++) {
          var start = Math.round((leadIn + b * period) * sr);
          var accent = accentEvery > 0 && b % accentEvery === 0;
          var freq = accent ? 1600 : 1000;
          var gain = accent ? 0.9 : 0.55;
          for (var i = 0; i < clickSamples && start + i < length; i++) {
            // Exponential decay keeps the transient sharp, so the perceived
            // onset sits at the sample index rather than smeared after it.
            var env = Math.exp(-18.0 * (i / sr) / clickSeconds);
            data[start + i] += gain * env * Math.sin((2 * Math.PI * freq * i) / sr);
          }
        }

        this.buffer = buffer;
        this.status = "ready";
        this.error = "";
        log("OK", "audio: click track built - " + beats + " beats at " + bpm +
          " BPM, " + buffer.duration.toFixed(2) + "s, " + sr + "Hz");
        return true;
      } catch (e) {
        this.status = "error";
        this.error = String(e);
        log("FAIL", "audio: click track failed: " + e);
        return false;
      }
    },

    /* Fetch and decode an audio file. Async work stays here; Python polls
     * status(). */
    loadUrl: function (url) {
      if (!this.init()) return false;
      var self = this;
      self.status = "loading";
      self.error = "";
      fetch(url)
        .then(function (response) {
          if (!response.ok) {
            throw new Error("HTTP " + response.status + " for " + url);
          }
          return response.arrayBuffer();
        })
        .then(function (raw) {
          return self.ctx.decodeAudioData(raw);
        })
        .then(
          function (decoded) {
            self.buffer = decoded;
            self.status = "ready";
            log("OK", "audio: decoded " + url + " (" +
              decoded.duration.toFixed(2) + "s, " + decoded.sampleRate + "Hz)");
          },
          function (e) {
            self.status = "error";
            self.error = String(e);
            log("FAIL", "audio: could not load " + url + ": " + e);
          }
        );
      return true;
    },

    /* Start playback from ``offset`` seconds into the buffer.
     *
     * ``lead`` schedules the start slightly in the future so the graph has
     * time to be wired before the first sample is due; position() reports
     * negative values until then, which is a real count-in rather than a
     * special case. */
    play: function (offset, lead) {
      if (!this.buffer || !this.ctx) return false;
      try {
        this.stop();
        offset = offset || 0;
        lead = lead === undefined ? 0.12 : lead;

        var source = this.ctx.createBufferSource();
        source.buffer = this.buffer;
        source.connect(this.ctx.destination);

        var when = this.ctx.currentTime + lead;
        source.start(when, offset);

        this.source = source;
        this.t0 = when;
        this.startOffset = offset;
        this.pausedAt = null;
        this.status = "playing";
        return true;
      } catch (e) {
        this.status = "error";
        this.error = String(e);
        log("FAIL", "audio: play failed: " + e);
        return false;
      }
    },

    stop: function () {
      if (this.source) {
        try {
          this.source.onended = null;
          this.source.stop();
        } catch (e) {
          /* already stopped */
        }
        try {
          this.source.disconnect();
        } catch (e) {
          /* nothing connected */
        }
        this.source = null;
      }
      if (this.status === "playing") this.status = "stopped";
      return true;
    },

    pause: function () {
      if (this.status !== "playing") return false;
      this.pausedAt = this.position();
      this.stop();
      this.status = "paused";
      return true;
    },

    resume: function () {
      if (this.status !== "paused") return false;
      return this.play(Math.max(0, this.pausedAt || 0), 0.06);
    },

    /* Playback position in seconds, corrected for output latency so it means
     * "what is reaching the speakers now". Negative during the lead-in. */
    position: function () {
      if (!this.ctx) return 0;
      if (this.status === "paused") return this.pausedAt || 0;
      if (this.status !== "playing") return this.startOffset || 0;
      return this.ctx.currentTime - this.t0 + this.startOffset - this.latency();
    },

    /* Raw context clock, for measuring input timestamps against the same
     * time base without the latency correction applied twice. */
    contextTime: function () {
      return this.ctx ? this.ctx.currentTime : 0;
    },

    duration: function () {
      return this.buffer ? this.buffer.duration : 0;
    },

    sampleRate: function () {
      return this.ctx ? this.ctx.sampleRate : 0;
    },

    state: function () {
      return this.status;
    },

    lastError: function () {
      return this.error;
    },

    contextState: function () {
      return this.ctx ? this.ctx.state : "none";
    },
  };

  window.piuAudio = piuAudio;
  log("BOOT", "audio bridge installed");
})();

/* piu input timestamping.
 *
 * Lives beside the audio bridge because its whole purpose is to stamp key
 * events against the *audio* clock rather than a wall clock.
 *
 * Reading input once per frame quantises it by up to a frame - about 5ms of
 * standard deviation at 60Hz, before any real jitter is counted. Capturing the
 * DOM keydown as it happens and stamping it with AudioContext.currentTime
 * removes that entirely, and puts the input on the same time base as the song
 * position so the two can be subtracted without correcting twice.
 *
 * Python drains the queue once per frame; the timestamps stay true regardless
 * of when that happens.
 */
(function () {
  "use strict";

  var QUEUE = [];
  var MAX_QUEUE = 512;
  var enabled = false;

  function stamp() {
    // Latency-corrected position, matching what SongClock.position reports,
    // so an offset is input-minus-expected with no further adjustment.
    return window.piuAudio ? window.piuAudio.position() : 0;
  }

  function onKey(event, down) {
    if (!enabled) return;
    if (event.repeat) return;
    if (QUEUE.length >= MAX_QUEUE) QUEUE.shift();
    QUEUE.push({
      code: event.code || "",
      key: event.key || "",
      down: down,
      t: stamp(),
    });
  }

  window.addEventListener("keydown", function (e) { onKey(e, true); }, true);
  window.addEventListener("keyup", function (e) { onKey(e, false); }, true);

  window.piuInput = {
    enable: function () {
      enabled = true;
      QUEUE.length = 0;
      return true;
    },
    disable: function () {
      enabled = false;
      QUEUE.length = 0;
      return true;
    },
    /* Drain the queue as a flat array: code, down flag, timestamp, repeating.
     * Flat because a list of numbers and strings crosses the pygbag bridge far
     * more predictably than an array of objects. */
    drain: function () {
      var flat = [];
      for (var i = 0; i < QUEUE.length; i++) {
        flat.push(QUEUE[i].code, QUEUE[i].down ? 1 : 0, QUEUE[i].t);
      }
      QUEUE.length = 0;
      return flat;
    },
    pending: function () {
      return QUEUE.length;
    },
  };

  if (window.piuBootLog) window.piuBootLog("BOOT", "input timestamping installed");
})();
