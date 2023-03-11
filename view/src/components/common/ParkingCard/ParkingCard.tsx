import CancelIcon from '@mui/icons-material/Cancel'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import { Card, ButtonBase } from '@mui/material'
import { Chart, registerables } from 'chart.js'
import { useState, useMemo } from 'react'
import { Line } from 'react-chartjs-2'

import { ParkingCardProps } from './ParkingCard.type'
import { Modal } from '../Modal'


const ParkingCard = ({ name, maxCapacity, currentCapacity, data }: ParkingCardProps) => {
  Chart.register(...registerables)

  const [isOpen, setIsOpen] = useState(false)
  const chartData = useMemo(() => ({
      labels:
        data &&
        data.map((d) => {
          const date = new Date(d.time)
          return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
        }),
      datasets: [
        {
          label: name,
          data: data && data.map((d) => d.currentCapacity),
        },
      ],
    }), [data, name])

  return (
    <>
      <Modal title={name} isOpen={isOpen} onClose={() => setIsOpen(false)}>
        <div className='flex flex-col items-center justify-center'>
          <div className='flex flex-row items-end gap-3'>
            <p className={`${currentCapacity === maxCapacity ? 'text-accent' : 'text-secondary'} text-3xl font-bold`}>
              {currentCapacity} 台
            </p>
            <p> / </p>
            <p>{maxCapacity} 台</p>
          </div>

          <Line
            data={chartData}
            options={{
              plugins: {
                legend: {
                  display: false,
                },
              },
              scales: {
                y: {
                  max: maxCapacity,
                },
              },
              animation: false,
            }}
            className='md:p-10'
          />
        </div>
      </Modal>
      <ButtonBase onClick={() => setIsOpen(true)}>
        <Card
          sx={{
            p: '1rem',
            backgroundColor: 'white',
            display: 'flex',
            flexDirection: 'column',
            gap: '1rem',
            minWidth: '300px',
          }}
          // hoverしたら浮かして影をつける
          className='transition-all hover:-translate-y-1 hover:shadow-lg'
        >
          <h1 className='mr-auto text-xl font-bold'>{name}</h1>
          <div className='flex flex-row items-center justify-around'>
            <div className='flex flex-col items-center justify-center'>
              <p
                className={`${
                  currentCapacity === maxCapacity ? 'text-accent' : 'text-secondary'
                } m-3 text-3xl font-bold`}
              >
                {currentCapacity} 台
              </p>
              <p className='text-sm'>/ {maxCapacity} 台中</p>
            </div>
            <CheckCircleIcon
              fontSize='large'
              className={`${currentCapacity === maxCapacity ? 'hidden' : 'block'} text-secondary`}
            />
            <CancelIcon
              fontSize='large'
              className={`${currentCapacity !== maxCapacity ? 'hidden' : 'block'} text-accent`}
            />
          </div>
          <div className='ml-auto flex flex-col items-end gap-2'>
            <p className='text-xs'>クリックで詳細</p>
          </div>
        </Card>
      </ButtonBase>
    </>
  )
}

export default ParkingCard