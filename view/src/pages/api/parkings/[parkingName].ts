import { NextApiRequest, NextApiResponse } from 'next'

import { isParkingName } from '@/constants/parkingNames'
import { connectToDatabase } from '@/utils/mongodb'

const handler = async (req: NextApiRequest, res: NextApiResponse) => {
  try {
    const { method } = req
    const { parkingName } = req.query
    if (typeof parkingName !== 'string') throw new Error('parkingName is not string')
    if (!isParkingName(parkingName)) throw new Error('parkingName is not valid')

    switch (method) {
      case 'GET': {
        const { db } = await connectToDatabase()
        const data = await db.collection(parkingName).find().toArray()

        res.status(200).json(data)
        break
      }
      default:
        res.setHeader('Allow', ['GET', 'PUT'])
        if (method) res.status(405).end(`Method ${method} Not Allowed`)
        else res.status(405).end(`Method Not Allowed`)
    }
  } catch (err) {
    res.status(500).json({ statusCode: 500, message: (err as Error).message })
  }
}

export default handler
