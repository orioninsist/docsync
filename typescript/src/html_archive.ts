import { createHash, randomUUID } from 'node:crypto';
import { link, mkdir, open, readFile, unlink } from 'node:fs/promises';
import path from 'node:path';

export type HtmlArchive = {
  file: string;
  sha256: string;
};

export async function archiveHtml(
  html: string,
  stateDir: string,
): Promise<HtmlArchive> {
  const data = Buffer.from(html, 'utf8');
  const digest = createHash('sha256').update(data).digest('hex');

  const directory = path.join(stateDir, 'html', 'sha256', digest.slice(0, 2));
  const target = path.join(directory, `${digest}.html`);

  await mkdir(directory, { recursive: true });

  const verify = async (): Promise<void> => {
    const existing = await readFile(target);
    const actual = createHash('sha256').update(existing).digest('hex');

    if (actual !== digest) {
      throw new Error(`HTML archive integrity failure: ${target}`);
    }
  };

  try {
    await verify();
    return { file: target, sha256: digest };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
      throw error;
    }
  }

  const temporary = path.join(
    directory,
    `.docsync-${randomUUID()}.tmp`,
  );

  const handle = await open(temporary, 'wx');

  try {
    await handle.writeFile(data);
    await handle.sync();
  } finally {
    await handle.close();
  }

  try {
    try {
      await link(temporary, target);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST') {
        throw error;
      }

      await verify();
    }
  } finally {
    await unlink(temporary);
  }

  return { file: target, sha256: digest };
}
