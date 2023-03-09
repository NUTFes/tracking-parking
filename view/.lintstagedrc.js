module.exports = {
  '**/*.{ts,tsx,css,scss}': (filenames) =>
    `prettier --write ${filenames.map((file) => file.split(process.cwd())[1].slice(1)).join(' ')}`,
  '**/*.{ts,tsx}': (filenames) =>
    `eslint ${filenames.map((file) => file.split(process.cwd())[1].slice(1)).join(' ')} --fix`,
}
