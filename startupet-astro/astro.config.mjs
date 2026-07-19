import { defineConfig } from 'astro/config';

// Static output; the whole point of Option B is zero server runtime + zero
// React hydration. Astro ships HTML+CSS by default and only the tiny GSAP
// init as a client script.
export default defineConfig({
  site: 'https://startupet.et',
  build: { inlineStylesheets: 'never' },
  devToolbar: { enabled: false },
});
