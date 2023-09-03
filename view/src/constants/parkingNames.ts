export const parkings = [
  {
    nameJP: '中央',
    name: 'central',
    limit: 96,
  },
  {
    nameJP: '生物',
    name: 'bionics',
    limit: 40,
  },
  // {
  //   nameJP: '電気',
  //   name: 'electronics',
  //   limit: 44,
  // },
  {
    nameJP: '講義棟西1',
    name: 'lecture_west1',
    limit: 48,
  },
  // {
  //   nameJP: '講義棟西2',
  //   name: 'lecture_west2',
  //   limit: 44,
  // },
  {
    nameJP: '講義棟北',
    name: 'lecture_north',
    limit: 44 + 159, // 講義棟北2, 3の合計
  },
]

export type ParkingName = (typeof parkings)[number]['name']

export const isParkingName = (arg: string): arg is ParkingName => parkings.some((parking) => parking.name === arg)
