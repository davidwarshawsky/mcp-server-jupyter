import * as path from 'path';
import Mocha from 'mocha';
import { glob } from 'glob';

export function run(): Promise<void> {
  // Create the mocha test
  const mocha = new Mocha({
    ui: 'tdd',
    color: true,
    timeout: 10000, // 10 second timeout for each test
  });

  const testsRoot = path.resolve(__dirname, '..');
  // Note: most tests live under test/suite -> out/test/suite.
  // Some targeted tests may live under src/test/suite -> out/src/test/suite.
  const srcTestsRoot = path.resolve(__dirname, '../../src/test');

  return new Promise((resolve, reject) => {
    Promise.all([
      glob('**/**.test.js', { cwd: testsRoot }),
      // Only include the GC lifecycle test from src tests to avoid pulling in legacy/unused suites.
      glob('suite/garbageCollection.test.js', { cwd: srcTestsRoot })
    ]).then(([testFiles, gcFiles]) => {
      // Add files to the test suite
      testFiles.forEach((f: string) => mocha.addFile(path.resolve(testsRoot, f)));
      gcFiles.forEach((f: string) => mocha.addFile(path.resolve(srcTestsRoot, f)));

      try {
        // Run the mocha test
        mocha.run((failures: number) => {
          if (failures > 0) {
            reject(new Error(`${failures} tests failed.`));
          } else {
            resolve();
          }
        });
      } catch (err) {
        console.error(err);
        reject(err);
      }
    }).catch(reject);
  });
}
