/**
 * esbuild.renderer.mjs
 * 
 * Builds the notebook output renderer for browser context.
 * Produces: out/renderer.js (single bundled file)
 */
import * as esbuild from 'esbuild';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));

const isWatch = process.argv.includes('--watch');

/** @type {esbuild.BuildOptions} */
const buildOptions = {
  entryPoints: [join(__dirname, 'src/renderer.ts')],
  bundle: true,
  outfile: join(__dirname, 'out/renderer.js'),
  format: 'esm',
  platform: 'browser',
  target: 'es2020',
  sourcemap: true,
  minify: !isWatch,
  external: [],
  define: {
    'process.env.NODE_ENV': isWatch ? '"development"' : '"production"'
  }
};

async function build() {
  if (isWatch) {
    const ctx = await esbuild.context(buildOptions);
    await ctx.watch();
    console.log('👀 Watching renderer for changes...');
  } else {
    await esbuild.build(buildOptions);
    console.log('✅ Renderer built: out/renderer.js');
  }
}

build().catch((e) => {
  console.error('❌ Renderer build failed:', e);
  process.exit(1);
});
