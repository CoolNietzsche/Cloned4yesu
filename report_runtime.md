# Runtime Audit Report

Base URL used: `http://127.0.0.1:8890/`

## Page: `/`

URL: http://127.0.0.1:8890/

### Console: 0 error(s), 0 warning(s)

_None._

### Uncaught JS Exceptions (1)

- `Minified React error #418; visit https://react.dev/errors/418?args[]=HTML&args[]= for the full message or use the non-minified dev environment for full errors and additional helpful warnings.`

### Failed Network Requests: 1 total (1 functional, 0 cosmetic)

**Functional (likely breaks something):**

| url | status/failure | resource_type |
|---|---|---|
| http://127.0.0.1:8890/video/900x1280_menu.mp4 | net::ERR_ABORTED | media |

### Interactive Elements Probe

- **Nav menu toggle:** found. ✅ responded to click (class/attr/visibility changed)
- **Slider/carousel:** found, next-button found. ❌ SILENT FAILURE — next button click produced no DOM change
- **Video elements:** 1 found
  - ✅ `http://127.0.0.1:8890/video/900x1280_menu.mp4` — loaded OK (readyState=4, 900x1280)
- **Custom cursor effect:** found. ❌ SILENT FAILURE — no style change on mousemove (cursor effect likely dead)
- **Forms:** none on this page

## Page: `/404/`

URL: http://127.0.0.1:8890/404/

### Console: 0 error(s), 0 warning(s)

_None._

### Uncaught JS Exceptions (1)

- `Minified React error #418; visit https://react.dev/errors/418?args[]=HTML&args[]= for the full message or use the non-minified dev environment for full errors and additional helpful warnings.`

### Failed Network Requests: 0 total (0 functional, 0 cosmetic)

### Interactive Elements Probe

- **Nav menu toggle:** found. ✅ responded to click (class/attr/visibility changed)
- **Slider/carousel:** not found on this page
- **Video elements:** 1 found
  - ✅ `http://127.0.0.1:8890/video/900x1280_menu.mp4` — loaded OK (readyState=4, 900x1280)
- **Custom cursor effect:** found. ❌ SILENT FAILURE — no style change on mousemove (cursor effect likely dead)
- **Forms:** none on this page

## Page: `/_next/image/index__P3VybD0lMkZpbWclMkZ3b3JrcyUyRjE5MjB4MTI4`

URL: http://127.0.0.1:8890/_next/image/index__P3VybD0lMkZpbWclMkZ3b3JrcyUyRjE5MjB4MTI4

### Console: 1 error(s), 0 warning(s)

| type | text | location |
|---|---|---|
| error | Failed to load resource: the server responded with a status of 404 (File not found) | http://127.0.0.1:8890/_next/image/index__P3VybD0lMkZpbWclMkZ3b3JrcyUyRjE5MjB4MTI4:0 |

### Failed Network Requests: 1 total (1 functional, 0 cosmetic)

**Functional (likely breaks something):**

| url | status/failure | resource_type |
|---|---|---|
| http://127.0.0.1:8890/_next/image/index__P3VybD0lMkZpbWclMkZ3b3JrcyUyRjE5MjB4MTI4 | 404 | document |

### Interactive Elements Probe

- **Nav menu toggle:** not found on this page (may not apply)
- **Slider/carousel:** not found on this page
- **Video elements:** none on this page
- **Custom cursor effect:** not found on this page
- **Forms:** none on this page

## Page: `/about-me/`

URL: http://127.0.0.1:8890/about-me/

### Console: 0 error(s), 0 warning(s)

_None._

### Uncaught JS Exceptions (1)

- `Minified React error #418; visit https://react.dev/errors/418?args[]=HTML&args[]= for the full message or use the non-minified dev environment for full errors and additional helpful warnings.`

### Failed Network Requests: 0 total (0 functional, 0 cosmetic)

### Interactive Elements Probe

- **Nav menu toggle:** found. ✅ responded to click (class/attr/visibility changed)
- **Slider/carousel:** found, next-button found. ❌ SILENT FAILURE — next button click produced no DOM change
- **Video elements:** 1 found
  - ✅ `http://127.0.0.1:8890/video/900x1280_menu.mp4` — loaded OK (readyState=4, 900x1280)
- **Custom cursor effect:** found. ❌ SILENT FAILURE — no style change on mousemove (cursor effect likely dead)
- **Forms:** none on this page

## Page: `/about-us/`

URL: http://127.0.0.1:8890/about-us/

### Console: 0 error(s), 0 warning(s)

_None._

### Uncaught JS Exceptions (1)

- `Minified React error #418; visit https://react.dev/errors/418?args[]=HTML&args[]= for the full message or use the non-minified dev environment for full errors and additional helpful warnings.`

### Failed Network Requests: 0 total (0 functional, 0 cosmetic)

### Interactive Elements Probe

- **Nav menu toggle:** found. ✅ responded to click (class/attr/visibility changed)
- **Slider/carousel:** not found on this page
- **Video elements:** 1 found
  - ✅ `http://127.0.0.1:8890/video/900x1280_menu.mp4` — loaded OK (readyState=4, 900x1280)
- **Custom cursor effect:** found. ❌ SILENT FAILURE — no style change on mousemove (cursor effect likely dead)
- **Forms:** none on this page

## Page: `/blog-article/`

URL: http://127.0.0.1:8890/blog-article/

### Console: 0 error(s), 0 warning(s)

_None._

### Uncaught JS Exceptions (1)

- `Minified React error #418; visit https://react.dev/errors/418?args[]=HTML&args[]= for the full message or use the non-minified dev environment for full errors and additional helpful warnings.`

### Failed Network Requests: 0 total (0 functional, 0 cosmetic)

### Interactive Elements Probe

- **Nav menu toggle:** found. ✅ responded to click (class/attr/visibility changed)
- **Slider/carousel:** not found on this page
- **Video elements:** 1 found
  - ✅ `http://127.0.0.1:8890/video/900x1280_menu.mp4` — loaded OK (readyState=4, 900x1280)
- **Custom cursor effect:** found. ❌ SILENT FAILURE — no style change on mousemove (cursor effect likely dead)
- **Forms:** 1 found
  - method=get, action=http://127.0.0.1:8890/blog-article/, fields=3
