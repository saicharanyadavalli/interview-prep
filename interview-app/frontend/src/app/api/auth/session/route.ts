import { NextResponse } from 'next/server'
import { getCurrentSession } from '@/app/actions/auth'

export const dynamic = 'force-dynamic'

export async function GET() {
  const sessionData = await getCurrentSession()
  return NextResponse.json(sessionData)
}
