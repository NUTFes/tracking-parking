import { AppBar } from '@mui/material'

const Header = () => (
  <AppBar
    position='static'
    sx={{
      height: '4rem',
      display: 'flex',
      flexDirection: 'row',
      alignItems: 'center',
      px: '2rem',
      fontSize: '1.5rem',
    }}
    className='bg-primary text-textWhite'
  >
    TrackingParking
  </AppBar>
)

export default Header
