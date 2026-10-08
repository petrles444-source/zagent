import { PrismaClient } from '@prisma/client'

const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined
  __prismaSchemaVersion?: string
}

// Bump this whenever prisma/schema.prisma changes structurally
// (new model / new column). It busts the cached client so the dev
// server picks up the new fields without a full process restart.
const SCHEMA_VERSION = 'v5-nowplaying-2026-10'

export const db = (() => {
  if (
    globalForPrisma.prisma &&
    globalForPrisma.__prismaSchemaVersion === SCHEMA_VERSION
  ) {
    return globalForPrisma.prisma
  }
  const client = new PrismaClient({
    log: ['query'],
  })
  globalForPrisma.prisma = client
  globalForPrisma.__prismaSchemaVersion = SCHEMA_VERSION
  return client
})()
