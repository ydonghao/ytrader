# YTrader Frontend

Quantitative Trading Platform Frontend built with React 18, TypeScript, and modern frontend technology stack.

## Technology Stack

- **Framework**: React 18 + TypeScript
- **Build Tool**: Rsbuild
- **Package Manager**: Rush + PNPM
- **Routing**: React Router v7
- **State Management**: Zustand
- **Internationalization**: i18next

## Project Architecture

```
frontend/
├── apps/                    # Application layer
│   └── web/               # Main trading platform
├── packages/               # Core packages
│   ├── arch/              # Architecture infrastructure (level-1)
│   │   ├── api/           # API client
│   │   ├── hooks/         # React hooks
│   │   ├── i18n/          # Internationalization
│   │   └── utils/         # Utilities
│   ├── common/            # Common components (level-2)
│   │   ├── components/    # UI component library
│   │   └── utils/         # Common utilities
│   └── trading/           # Trading domain (level-3)
│       ├── strategy/       # Strategy management
│       ├── portfolio/      # Portfolio management
│       └── market-data/    # Market data module
├── config/                # Configuration files
│   ├── eslint-config/     # ESLint configuration
│   ├── rsbuild-config/    # Rsbuild build configuration
│   └── tsconfig/         # TypeScript configuration
└── infra/                 # Infrastructure tools (future)
```

## Package Hierarchy

1. **arch/ (Level 1)**: Foundation packages - no dependencies on other internal packages
2. **common/ (Level 2)**: Shared components and utilities
3. **trading/ (Level 3)**: Domain-specific modules
4. **apps/ (Level 4)**: Main application

## Getting Started

### Prerequisites

- Node.js >= 21
- PNPM 8.15.8
- Rush 5.147.1

### Installation

```bash
# Install Rush globally if not already installed
npm install -g @microsoft/rush

# Install dependencies
rush install

# or use pnpm directly
pnpm install
```

### Development

```bash
# Start development server
cd apps/web
pnpm dev

# or from root
rushx dev
```

### Build

```bash
# Build all packages
rush build

# Build specific package
cd packages/arch/api
pnpm build
```

### Lint

```bash
# Lint all packages
rush lint

# Lint specific package
cd apps/web
pnpm lint
```

## Features

### Dashboard
- Portfolio overview with equity and P&L metrics
- Active positions summary
- Strategy performance indicators

### Market
- Real-time ticker prices
- K-Line candlestick charts
- Order book depth view
- Trade history

### Trading
- Order placement (Limit/Market)
- Open orders management
- Order history
- Account balance display

### Strategies
- Strategy creation and management
- Multiple strategy types (Grid, DCA, Momentum, etc.)
- Strategy start/stop controls
- Performance statistics

### Portfolio
- Position management
- Account balance overview
- Unrealized/Realized P&L tracking

### Settings
- Theme toggle (Dark/Light)
- Language selection
- API configuration

## Design System

The frontend uses a custom design system with:

- **Dark Theme**: Default trading terminal aesthetic
- **Typography**: JetBrains Mono for data, Inter for UI
- **Colors**:
  - Background: `#0a0e14`
  - Surface: `#111822`
  - Accent: `#58a6ff`
  - Success: `#3fb950`
  - Danger: `#f85149`

## Environment Variables

Create `.env.local` in `apps/web/`:

```
VITE_API_BASE_URL=http://localhost:8080/api/v1
VITE_WS_URL=ws://localhost:8080/ws
```

## License

Proprietary - All rights reserved
