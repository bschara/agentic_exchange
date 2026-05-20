import { cn } from '@/lib/utils';
import { ButtonHTMLAttributes } from 'react';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'outline' | 'ghost';
  size?: 'default' | 'sm' | 'lg';
}

export function Button({ className, variant = 'default', size = 'default', ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center rounded-lg text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50',
        variant === 'default' && 'bg-gray-100 text-gray-900 hover:bg-gray-200',
        variant === 'outline' && 'border border-gray-700 bg-transparent text-gray-200 hover:bg-gray-800',
        variant === 'ghost' && 'bg-transparent text-gray-200 hover:bg-gray-800',
        size === 'default' && 'h-9 px-4 py-2',
        size === 'sm' && 'h-7 px-3 text-xs',
        size === 'lg' && 'h-11 px-8',
        className
      )}
      {...props}
    />
  );
}
