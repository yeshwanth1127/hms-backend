import { createInterface } from 'node:readline';
import { createDemoEngine } from './engine.mjs';

const engine = createDemoEngine();
const terminal = createInterface({ input: process.stdin, output: process.stdout, prompt: 'You> ' });
const from = 'local-simulator';
let messageNumber = 0;

console.log('WhatsApp booking demo simulator. Type “hi” to start, “:followup” for a test follow-up, or “:quit”.');
terminal.prompt();
terminal.on('line', (line) => {
  const input = line.trim();
  if (input === ':quit') return terminal.close();
  if (input === ':followup') {
    console.log(`Bot> ${engine.followup(from) ?? 'No open test conversation.'}`);
  } else {
    messageNumber += 1;
    const media = input.match(/^:media\s+(image|document|video|audio|sticker)$/i);
    const reply = engine.handle({
      id: `sim-${messageNumber}`, from,
      type: media ? media[1].toLowerCase() : 'text', text: media ? '' : input,
    });
    console.log(`Bot> ${reply}`);
  }
  terminal.prompt();
});
