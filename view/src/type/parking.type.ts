export interface Parking {
    _id: string
    count: number
    time: number
}

export interface ParkingData {
    name: string
    data: Parking[]
}
