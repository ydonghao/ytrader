import React, {HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes, forwardRef} from 'react';
import clsx from 'clsx';
import './Table.css';

export interface TableProps extends HTMLAttributes<HTMLTableElement> {
  variant?: 'default' | 'striped' | 'compact';
}

export const Table = forwardRef<HTMLTableElement, TableProps>(
  ({className, variant = 'default', ...props}, ref) => {
    return (
      <table
        ref={ref}
        className={clsx('table', `table--${variant}`, className)}
        {...props}
      />
    );
  }
);

Table.displayName = 'Table';

export interface TableHeadProps extends HTMLAttributes<HTMLTableSectionElement> {}

export const TableHead = forwardRef<HTMLTableSectionElement, TableHeadProps>(
  ({className, ...props}, ref) => {
    return <thead ref={ref} className={clsx('table__head', className)} {...props} />;
  }
);

TableHead.displayName = 'TableHead';

export interface TableBodyProps extends HTMLAttributes<HTMLTableSectionElement> {}

export const TableBody = forwardRef<HTMLTableSectionElement, TableBodyProps>(
  ({className, ...props}, ref) => {
    return <tbody ref={ref} className={clsx('table__body', className)} {...props} />;
  }
);

TableBody.displayName = 'TableBody';

export interface TableRowProps extends HTMLAttributes<HTMLTableRowElement> {}

export const TableRow = forwardRef<HTMLTableRowElement, TableRowProps>(
  ({className, ...props}, ref) => {
    return <tr ref={ref} className={clsx('table__row', className)} {...props} />;
  }
);

TableRow.displayName = 'TableRow';

export interface TableCellProps extends TdHTMLAttributes<HTMLTableCellElement> {
  numeric?: boolean;
}

export const TableCell = forwardRef<HTMLTableCellElement, TableCellProps>(
  ({className, numeric = false, ...props}, ref) => {
    return (
      <td
        ref={ref}
        className={clsx('table__cell', {'table__cell--numeric': numeric}, className)}
        {...props}
      />
    );
  }
);

TableCell.displayName = 'TableCell';

export interface TableHeaderCellProps extends ThHTMLAttributes<HTMLTableCellElement> {
  numeric?: boolean;
}

export const TableHeaderCell = forwardRef<HTMLTableCellElement, TableHeaderCellProps>(
  ({className, numeric = false, ...props}, ref) => {
    return (
      <th
        ref={ref}
        className={clsx('table__header-cell', {'table__header-cell--numeric': numeric}, className)}
        {...props}
      />
    );
  }
);

TableHeaderCell.displayName = 'TableHeaderCell';
