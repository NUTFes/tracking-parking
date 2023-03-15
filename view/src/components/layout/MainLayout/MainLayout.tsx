import { Header } from '@/components/common'

import { MainLayoutProps } from './MainLayout.type'

const MainLayout = ({ children }: MainLayoutProps) => (
    <>
      <Header />
      {children}
    </>
  )

export default MainLayout
