import { Card, Typography } from '@mui/material'
import { NextPage } from 'next'
import Image from 'next/image'

import { ParkingCard } from '@/components/common'
import { parkingNames, parkingLimit } from '@/constants/parkingNames'
import { ParkingData, Parking } from '@/type/parking.type'

interface Props {
  parkingData: ParkingData[]
}

export const getServerSideProps = async () => {
  const parkingData = await Promise.all(
    parkingNames.map(async (name) => {
      const url = `http://view:3000/api/parkings/${name}`
      const res = await fetch(url)
      
      if (res.status !== 200) {
        throw new Error(`Failed to fetch ${url}`)
      }
      const data = await res.json() as Parking[]
      return { 
        name,
        data,
      }
    }),
  )

  return {
    props: {
      parkingData,
    },
  }
}

export const Home: NextPage<Props> = ({ parkingData }: Props) => (
  <main>
    <div className='my-10 flex flex-col items-center'>
      <Card
        sx={{
          width: 'fit-content',
          p: '2rem',
          mxnWidth: '90%',
          display: 'flex',
          flexDirection: 'column',
          gap: '2rem',
          alignItems: 'center',
          boxShadow: '0 0 10px 0 rgba(0, 0, 0, 0.2)',
        }}
        className='bg-white text-textBlack'
      >
        <div className='w-4/5'>
          <Image src='/images/map.png' alt='map' width={500} height={500} className='w-full' />
        </div>
        <Typography variant='h5' fontWeight='bold'>
          現在の駐車状況
        </Typography>
        <div className='gird-cols-1 grid gap-5 md:grid-cols-3'>
          {parkingData.map(({ name, data }, index) => (
            <ParkingCard key={name} name={name} currentCapacity={data[data.length-1].count} maxCapacity={parkingLimit[index]} data={data} />
          ))}
        </div>
      </Card>
    </div>
  </main>
)

export default Home
