/**
 * Shared prayer line expansion for the kiosk app and cue-review editor.
 * Authoring unit = one audioCue. We only width-wrap; we do not re-split
 * authored cues on punctuation (the editor / essay already chose breaks).
 *
 * Wrap-continuation lines take their start from:
 * 1) cue.wordTiming[tokenIndex] (Whisper-aligned, preferred)
 * 2) cue.wordStarts[firstToken] (legacy map)
 * 3) interpolation across the cue's spoken [start, end] window
 */
(function (global) {
  const MONTH_NAMES =
    "january|february|march|april|may|june|july|august|september|october|november|december";

  function measureTextWidth(text, font) {
    if (!measureTextWidth.canvas) {
      measureTextWidth.canvas = document.createElement("canvas");
    }
    const ctx = measureTextWidth.canvas.getContext("2d");
    ctx.font = font;
    return ctx.measureText(text).width;
  }

  function getPrayerLineMetrics(viewport) {
    const width =
      (viewport && viewport.width) ||
      (global.kiosk && global.kiosk.clientWidth) ||
      global.innerWidth ||
      1080;
    const height =
      (viewport && viewport.height) ||
      (global.kiosk && global.kiosk.clientHeight) ||
      global.innerHeight ||
      1920;
    const rootSize =
      parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    // Match .poem-line: clamp(1.05rem, 3vh, 1.45rem)
    // The app's CSS uses 3vh (window height), not kiosk height, so we
    // approximate using global.innerHeight.
    const vhHeight = global.innerHeight || height || 1920;
    const fontSize = Math.min(
      1.45 * rootSize,
      Math.max(1.05 * rootSize, vhHeight * 0.03)
    );
    const wrapFraction = Number(
      (viewport && viewport.wrapFraction) ||
        global.PrayerLinesDefaultWrapFraction ||
        0.48
    );
    const fraction = Math.min(0.85, Math.max(0.28, wrapFraction || 0.48));
    // Optional absolute override (editor ruler / tests).
    const maxWidth =
      viewport && Number.isFinite(Number(viewport.maxWidth))
        ? Number(viewport.maxWidth)
        : width * fraction;
    return {
      maxWidth,
      font: `400 ${fontSize}px "Bona Nova", Georgia, serif`,
      wrapFraction: fraction,
      width,
      height,
      fontSize,
    };
  }

  function tokenize(text) {
    return String(text || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
  }

  function tokenKey(word) {
    return String(word || "")
      .trim()
      .replace(/^[^a-zA-Z0-9']+|[^a-zA-Z0-9']+$/g, "")
      .toLowerCase()
      .replace(/[’‘]/g, "'");
  }

  function buildWrapAtoms(text) {
    let protectedText = String(text || "").trim();
    if (!protectedText) return [];

    const glue = (match) => match.replace(/\s+/g, "\u00A0");

    protectedText = protectedText
      .replace(/\b(?:St|Mr|Mrs|Ms|Dr|Jr|Sr)\.\s+[A-Z][A-Za-z'’-]+/g, glue)
      .replace(
        new RegExp(
          `\\b(?:${MONTH_NAMES})\\.?\\s+\\d{1,2}(?:st|nd|rd|th)?(?:,)?\\s+\\d{4}\\b`,
          "gi"
        ),
        glue
      )
      .replace(
        new RegExp(
          `\\b(?:${MONTH_NAMES})\\.?\\s+\\d{1,2}(?:st|nd|rd|th)?\\b`,
          "gi"
        ),
        glue
      )
      .replace(
        /(\d{1,2}(?:st|nd|rd|th)?)\s+(\d{4})\b/gi,
        (_, day, year) => `${day}\u00A0${year}`
      )
      .replace(/\bMaybe it is somewhere\s+\S+/gi, glue)
      .replace(/\bSpirit has been calling me\b/gi, glue)
      .replace(/\bMy Nana has been calling me\b/gi, glue)
      .replace(/\b([A-Z][A-Za-z'’-]*)(?:\s+[A-Z][A-Za-z'’-]*)+\b/g, glue);

    return protectedText
      .split(/\s+/)
      .map((token) => token.replace(/\u00A0/g, " "));
  }

  function wrapLineToWidth(line, maxWidth, font) {
    const text = String(line || "").trim();
    if (!text) return [];
    if (measureTextWidth(text, font) <= maxWidth) return [text];

    const atoms = buildWrapAtoms(text);
    const rows = [];
    let current = "";

    const pushHardSplit = (word) => {
      let chunk = "";
      for (const ch of word) {
        const trial = chunk + ch;
        if (chunk && measureTextWidth(trial, font) > maxWidth) {
          rows.push(chunk);
          chunk = ch;
        } else {
          chunk = trial;
        }
      }
      current = chunk;
    };

    for (const atom of atoms) {
      const trial = current ? `${current} ${atom}` : atom;
      if (measureTextWidth(trial, font) <= maxWidth) {
        current = trial;
        continue;
      }
      if (current) rows.push(current);
      if (measureTextWidth(atom, font) <= maxWidth) {
        current = atom;
      } else {
        pushHardSplit(atom);
      }
    }

    if (current) rows.push(current);

    // Avoid orphan last rows (e.g. a lone "silenced.") when the prior row
    // can spare a couple of words.
    if (rows.length >= 2) {
      const last = rows[rows.length - 1];
      const prev = rows[rows.length - 2];
      const lastAtoms = last.split(/\s+/);
      const prevAtoms = prev.split(/\s+/);
      if (lastAtoms.length <= 2 && prevAtoms.length >= 4) {
        const moved = prevAtoms.pop();
        const candidatePrev = prevAtoms.join(" ");
        const candidateLast = `${moved} ${last}`.replace(/\s+/g, " ").trim();
        if (
          measureTextWidth(candidatePrev, font) <= maxWidth &&
          measureTextWidth(candidateLast, font) <= maxWidth
        ) {
          rows[rows.length - 2] = candidatePrev;
          rows[rows.length - 1] = candidateLast;
        }
      }
    }

    return rows;
  }

  function splitAtDisplayPunctuation(text) {
    const source = String(text || "").trim();
    if (!source) return [];
    const parts = [];
    let buffer = "";

    for (let i = 0; i < source.length; i += 1) {
      const ch = source[i];
      buffer += ch;
      if (![",", ";", ":", ".", "?", "!"].includes(ch)) continue;

      const next = source[i + 1];
      if (next !== undefined && !/\s/.test(next)) continue;
      if (
        ch === "." &&
        /\b(mr|mrs|ms|dr|st|jr|sr|vs|etc)\.$/i.test(buffer.trim())
      ) {
        continue;
      }

      const part = buffer.trim();
      if (part) parts.push(part);
      buffer = "";
      while (i + 1 < source.length && /\s/.test(source[i + 1])) i += 1;
    }

    const tail = buffer.trim();
    if (tail) parts.push(tail);
    return parts;
  }

  function wrapLineWithPunctuation(line, maxWidth, font) {
    const text = String(line || "").trim();
    if (!text) return [];
    if (measureTextWidth(text, font) <= maxWidth) return [text];

    const clauses = splitAtDisplayPunctuation(text);
    if (clauses.length <= 1) return wrapLineToWidth(text, maxWidth, font);

    const rows = [];
    clauses.forEach((clause) => {
      rows.push(...wrapLineToWidth(clause, maxWidth, font));
    });
    return rows;
  }

  function shouldMergePrayerUnits(prev, next) {
    const a = String(prev || "").trim();
    const b = String(next || "").trim();
    if (!a || !b) return false;

    const monthOrDay = new RegExp(
      `(?:${MONTH_NAMES}|\\d{1,2}(?:st|nd|rd|th)?)\\.?$`,
      "i"
    );
    const bareYear = /^\d{4}\.?$/;
    const startsWithYear = /^\d{4}\b/;

    if (bareYear.test(b) || (startsWithYear.test(b) && monthOrDay.test(a))) {
      return true;
    }
    if (startsWithYear.test(b) && !/[.!?]"?$/.test(a)) return true;
    if (/[,:;]$/.test(a)) return true;
    if (
      /\b(asking us|including|such as|and|or|the|a|an|of|to|for|with)$/i.test(a)
    ) {
      return true;
    }
    if (!/[.!?]"?$/.test(a) && /^[a-z(“']/.test(b)) return true;
    if (monthOrDay.test(a) && !/[.!?]"?$/.test(a)) return true;
    return false;
  }

  function coalesceAudioCues(cues) {
    const out = [];
    for (const cue of cues || []) {
      const text = String((cue && cue.text) || "").trim();
      if (!text) continue;
      if (!out.length) {
        out.push({ ...cue, text });
        continue;
      }
      const prev = out[out.length - 1];
      // Authored display lines from the cue editor keep their own start times.
      // Merging "…where I'm" + "going when…" would discard the going timestamp.
      if (prev.nowrap || cue.nowrap) {
        out.push({ ...cue, text });
        continue;
      }
      if (shouldMergePrayerUnits(prev.text, text)) {
        prev.text = `${prev.text} ${text}`.replace(/\s+/g, " ");
        if (Number.isFinite(Number(cue.end))) prev.end = Number(cue.end);
        if (Array.isArray(cue.wordTiming) && Array.isArray(prev.wordTiming)) {
          prev.wordTiming = prev.wordTiming.concat(cue.wordTiming);
        } else if (Array.isArray(cue.wordTiming)) {
          prev.wordTiming = cue.wordTiming.slice();
        }
        if (cue.wordStarts && typeof cue.wordStarts === "object") {
          prev.wordStarts = { ...(prev.wordStarts || {}), ...cue.wordStarts };
        }
        if (prev.nowrap && text.length > 8) delete prev.nowrap;
      } else {
        out.push({ ...cue, text });
      }
    }
    return out;
  }

  function spokenSpan(cue, start, nextStart) {
    const end = Number(cue && cue.end);
    if (Number.isFinite(end) && end > start) {
      return Math.max(0.25, end - start);
    }
    return Math.max(0.25, (Number(nextStart) || start + 2) - start);
  }

  function startForContinuation(opts) {
    const {
      line,
      tokenIndex,
      tokens,
      wordTiming,
      wordStarts,
      start,
      span,
    } = opts;

    if (
      Array.isArray(wordTiming) &&
      Number.isFinite(Number(wordTiming[tokenIndex]))
    ) {
      const locked = Number(wordTiming[tokenIndex]);
      // Failed alignments are often 0; never jump a mid-cue wrap before the cue.
      if (locked > start + 0.05) return locked;
    }

    const firstToken = tokenKey(tokenize(line)[0] || "");
    if (
      firstToken &&
      wordStarts &&
      Number.isFinite(Number(wordStarts[firstToken]))
    ) {
      const locked = Number(wordStarts[firstToken]);
      if (locked > start + 0.05) return locked;
    }

    const total = Math.max(1, tokens.length);
    return start + span * (tokenIndex / total);
  }

  function visualLinesForCue(cue, maxWidth, font, viewport) {
    const text = String((cue && cue.text) || "").trim();
    if (!text) return [];
    // Explicit nowrap keeps authored closing lines intact (e.g. Black Liberated Reality).
    if (cue && cue.nowrap) {
      return [text];
    }
    if (viewport && viewport.wrapMode === "punctuation") {
      return wrapLineWithPunctuation(text, maxWidth, font);
    }
    return wrapLineToWidth(text, maxWidth, font);
  }

  /**
   * Expand authored audio cues into timed visual carousel lines.
   * One cue = one authored line. Only width-wrapping may create extra visual rows.
   */
  function expandCuesToReadingLines(cues, viewport) {
    const { maxWidth, font } = getPrayerLineMetrics(viewport);
    const lines = [];
    const starts = [];
    const cueIndexForLine = [];
    const mergedCues = coalesceAudioCues(cues);

    mergedCues.forEach((cue, index) => {
      const text = String((cue && cue.text) || "").trim();
      if (!text) return;

      const start = Number(cue.start) || 0;
      const nextStart =
        index + 1 < mergedCues.length
          ? Number(mergedCues[index + 1].start) || start + 1.5
          : Number(cue.end) || start + 2;
      const span = spokenSpan(cue, start, nextStart);

      const visual = visualLinesForCue(cue, maxWidth, font, viewport);
      if (!visual.length) return;

      const tokens = tokenize(text);
      const wordTiming = Array.isArray(cue.wordTiming) ? cue.wordTiming : null;
      const wordStarts =
        cue.wordStarts && typeof cue.wordStarts === "object"
          ? cue.wordStarts
          : null;

      let tokenIndex = 0;
      visual.forEach((line, wrapIndex) => {
        lines.push(line);
        cueIndexForLine.push(index);
        const lineTokens = tokenize(line);

        if (wrapIndex === 0) {
          starts.push(start);
        } else {
          starts.push(
            startForContinuation({
              line,
              tokenIndex,
              tokens,
              wordTiming,
              wordStarts,
              start,
              span,
            })
          );
        }
        tokenIndex += lineTokens.length;
      });
    });

    return { lines, starts, cueIndexForLine, mergedCues };
  }

  /**
   * Turn authored cues into one editable cue per kiosk visual line.
   * Continuation starts use the same timing rules as expandCuesToReadingLines.
   * Resulting cues are marked nowrap so the app will not re-wrap them.
   */
  function flattenCuesToVisualLines(cues, viewport) {
    const { maxWidth, font } = getPrayerLineMetrics(viewport);
    const mergedCues = coalesceAudioCues(cues);
    const out = [];

    mergedCues.forEach((cue, index) => {
      const text = String((cue && cue.text) || "").trim();
      if (!text) return;

      const start = Number(cue.start) || 0;
      const nextCueStart =
        index + 1 < mergedCues.length
          ? Number(mergedCues[index + 1].start) || start + 1.5
          : Number(cue.end) || start + 2;
      const cueEnd = Number(cue.end);
      const end = Number.isFinite(cueEnd) && cueEnd > start ? cueEnd : nextCueStart;
      const span = spokenSpan(cue, start, nextCueStart);

      const visual = visualLinesForCue(cue, maxWidth, font, viewport);
      if (!visual.length) return;

      const tokens = tokenize(text);
      const wordTiming = Array.isArray(cue.wordTiming) ? cue.wordTiming : null;
      const wordStarts =
        cue.wordStarts && typeof cue.wordStarts === "object"
          ? cue.wordStarts
          : null;

      let tokenIndex = 0;
      for (let wrapIndex = 0; wrapIndex < visual.length; wrapIndex += 1) {
        const line = visual[wrapIndex];
        const lineTokens = tokenize(line);
        const lineStart =
          wrapIndex === 0
            ? start
            : startForContinuation({
                line,
                tokenIndex,
                tokens,
                wordTiming,
                wordStarts,
                start,
                span,
              });
        const lineEnd =
          wrapIndex + 1 < visual.length
            ? startForContinuation({
                line: visual[wrapIndex + 1],
                tokenIndex: tokenIndex + lineTokens.length,
                tokens,
                wordTiming,
                wordStarts,
                start,
                span,
              })
            : end;

        const slice = wordTiming
          ? wordTiming.slice(tokenIndex, tokenIndex + lineTokens.length)
          : null;
        const lineWordStarts = {};
        lineTokens.forEach((tok, i) => {
          const key = tokenKey(tok);
          if (!key) return;
          if (slice && Number.isFinite(Number(slice[i]))) {
            lineWordStarts[key] = Number(slice[i]);
          } else if (wordStarts && Number.isFinite(Number(wordStarts[key]))) {
            lineWordStarts[key] = Number(wordStarts[key]);
          }
        });

        const next = {
          text: line,
          start: Math.round(lineStart * 100) / 100,
          end: Math.round(lineEnd * 100) / 100,
          nowrap: true,
        };
        if (slice && slice.length) next.wordTiming = slice;
        if (Object.keys(lineWordStarts).length) next.wordStarts = lineWordStarts;
        out.push(next);
        tokenIndex += lineTokens.length;
      }
    });

    return out;
  }

  function splitOnSentencePunctuation(block) {
    const text = String(block || "").trim();
    if (!text) return [];
    const parts = [];
    let buf = "";
    for (let i = 0; i < text.length; i += 1) {
      const ch = text[i];
      buf += ch;
      if (ch !== "." && ch !== "?" && ch !== "!") continue;
      const next = text[i + 1];
      const endOfClause = next === undefined || /\s/.test(next);
      if (!endOfClause) continue;
      if (/\b(mr|mrs|ms|dr|st|jr|sr|vs|etc)\.$/i.test(buf.trim())) continue;
      const trimmed = buf.trim();
      if (trimmed) parts.push(trimmed);
      buf = "";
      while (i + 1 < text.length && /\s/.test(text[i + 1])) i += 1;
    }
    const tail = buf.trim();
    if (tail) parts.push(tail);
    return parts;
  }

  function coalescePrayerUnits(parts) {
    const out = [];
    for (const part of parts) {
      const text = String(part || "").trim();
      if (!text) continue;
      if (!out.length) {
        out.push(text);
        continue;
      }
      if (shouldMergePrayerUnits(out[out.length - 1], text)) {
        out[out.length - 1] = `${out[out.length - 1]} ${text}`.replace(
          /\s+/g,
          " "
        );
      } else {
        out.push(text);
      }
    }
    return out;
  }

  function splitPrayerSections(text, viewport) {
    const { maxWidth, font } = getPrayerLineMetrics(viewport);
    const sourceLines = coalescePrayerUnits(
      String(text || "")
        .replace(/\r\n/g, "\n")
        .split("\n")
        .flatMap((block) => splitOnSentencePunctuation(block.trim()))
        .filter(Boolean)
    );
    const fitted = [];
    sourceLines.forEach((line) => {
      fitted.push(...wrapLineToWidth(line, maxWidth, font));
    });
    return fitted;
  }

  global.PrayerLines = {
    getPrayerLineMetrics,
    wrapLineToWidth,
    expandCuesToReadingLines,
    flattenCuesToVisualLines,
    splitPrayerSections,
    coalesceAudioCues,
    splitOnSentencePunctuation,
    tokenKey,
    measureTextWidth,
    wrapLineWithPunctuation,
  };
  global.PrayerLinesDefaultWrapFraction = 0.48;
})(typeof window !== "undefined" ? window : globalThis);
