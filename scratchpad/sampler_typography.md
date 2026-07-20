# Typography sampler

This page exercises every block the compose renderer knows, so you can judge
legibility on the e-ink screen: font sizes, row height, rule contrast, and
margins. Inline styling like *emphasis*, **strong**, and `code` is flattened
to plain text in v1 — check whether that reads acceptably.

## Second-level heading

A normal paragraph that is long enough to wrap across several rows. The wrap
uses the renderer's own font metrics, so what you see here is exactly what
the manifest was measured against. If this text feels too small or too
large, that is a template constant we tune, not a redesign.

### Third-level heading

- first bullet item
- second bullet item that is deliberately much longer so it wraps onto a
  continuation row and you can judge the hanging indent
  - nested detail item
    - deeper item that flattens to depth two

1. first ordered step
2. second ordered step
3. third ordered step

> A quoted reminder rendered with a side bar and italics. Check whether the
> bar and the italic face are distinguishable at reading distance.

```
def targeted_read(page, bbox):
    return region_has_ink(mark, page, bbox)
```

---

| col a | col b |
|-------|-------|
| 1     | 2     |

![architecture diagram](diagram.png)

Closing paragraph with a long URL to test character breaking:
https://sn.siegpkm.com/some/very/long/path/that/cannot/word-wrap/0123456789
