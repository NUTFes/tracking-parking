import { Parking } from '@/type/parking.type'

export interface ParkingCardProps {
  name: string
  maxCapacity: number
  currentCapacity: number
  data?: Parking[]
  dataLimit?: number
}
