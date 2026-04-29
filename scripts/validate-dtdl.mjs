import { getInterop, validateDirectories } from '@digicatapult/dtdl-parser'

const dtdlDirectory = './dtdl'

const parser = await getInterop()
const isValid = validateDirectories(dtdlDirectory, parser, true)

if (!isValid) {
  console.error(`DTDL validation failed for '${dtdlDirectory}'`)
  process.exit(1)
}

console.log('DTDL validation passed')
