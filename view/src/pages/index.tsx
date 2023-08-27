import { Card, Typography } from '@mui/material'
import { NextPage } from 'next'
import Image from 'next/image'

import { ParkingCard } from '@/components/common'
import { parkings } from '@/constants/parkingNames'
import { ParkingData, Parking } from '@/type/parking.type'

interface Props {
  parkingData: ParkingData[]
}

export const getServerSideProps = async () => {
  const parkingData = await Promise.all(
    parkings.map(async ({ name, nameJP }) => {
      const url = `http://view:3000/api/parkings/${name}`
      const res = await fetch(url)

      if (res.status !== 200) {
        throw new Error(`Failed to fetch ${url}`)
      }
      const data = (await res.json()) as Parking[]
      return {
        name: nameJP,
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
          width: '90%',
          display: 'flex',
          flexDirection: 'column',
          gap: '2rem',
          alignItems: 'center',
          boxShadow: '0 0 10px 0 rgba(0, 0, 0, 0.2)',
        }}
        className='bg-white p-4 text-textBlack md:p-8'
      >
        <div className='flex w-full justify-center'>
          <Image src='/images/map.png' alt='map' width={500} height={500} className='w-full md:w-1/2' />
        </div>
        <Typography variant='h5' fontWeight='bold'>
          現在の駐車状況
        </Typography>
        <div className='gird-cols-1 grid gap-5 md:grid-cols-3'>
          {parkingData.map(({ name, data }, index) => {
            if (!data.length)
              return (
                <Card
                  sx={{
                    p: '1rem',
                    backgroundColor: 'white',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '1rem',
                    minWidth: '300px',
                  }}
                >
                  <div className='flex flex-col gap-4'>
                    <p className='text-xl'>{name}</p>
                    <p className='text-sm'>読み込みに失敗しました</p>
                  </div>
                </Card>
              )
            return (
              <ParkingCard
                key={name}
                name={name}
                currentCapacity={data[data.length - 1].count}
                maxCapacity={parkings[index].limit}
                data={data}
                dataLimit={20}
              />
            )
          })}
        </div>
      </Card>
    </div>
  </main>
)

export default Home
