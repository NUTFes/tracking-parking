export interface ParkingData {
  id: number
  currentCapacity: number
  time: string
}

export interface ParkingCardProps {
  name: string
  maxCapacity: number
  currentCapacity: number
  data?: ParkingData[]
}
