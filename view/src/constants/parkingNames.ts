export const parkingNames = ['twenty-four']
export const parkingLimit = [24]

export type ParkingName = (typeof parkingNames)[number]

export const isParkingName = (arg: string): arg is ParkingName => parkingNames.includes(arg)
