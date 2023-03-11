import { Card, Button } from '@mui/material'

import { ModalProps } from './Modal.type'

export const Modal = ({ title, children, isOpen, onClose }: ModalProps) => (
  <div className={`fixed top-0 left-0 z-50 h-full w-full bg-black bg-opacity-50 ${isOpen ? 'flex' : 'hidden'}`}>
    <div className='flex h-full w-full items-center justify-center'>
      <Card
        sx={{
          p: '1rem',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          boxShadow: '0 0 10px 0 rgba(0, 0, 0, 0.2)',
        }}
        className='w-9/10 bg-white text-textBlack md:w-1/2'
      >
        <Button onClick={onClose} sx={{ alignSelf: 'flex-end', fontSize: '1rem' }}>
          ×
        </Button>
        {title && <h1 className='text-2xl font-bold'>{title}</h1>}
        <div className='w-full p-3'>{children}</div>
      </Card>
    </div>
  </div>
)

export default Modal
