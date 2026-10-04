// The page: routing, the shared header and the session (plan 3.14, D39, D41, D59, D65).

import { call, session, whenSessionEnds } from './api.js';
import { loginScreen, signupScreen } from './auth.js';
import { h, icon } from './dom.js';
import { holdsScreen } from './holds.js';
import { requestsScreen } from './requests.js';
import { splitScreen } from './split-screen.js';
import { walletScreen } from './wallet.js';

const root = document.getElementById('app');

const NAV = [
  { path: '/', testid: 'nav-wallet', label: 'Wallet', icon: 'wallet' },
  { path: '/requests', testid: 'nav-requests', label: 'Requests', icon: 'requests' },
  { path: '/split', testid: 'nav-split', label: 'Split', icon: 'split' },
  { path: '/authorizations', testid: 'nav-authorizations', label: 'Holds', icon: 'hold' },
];
const SIGNED_IN = { '/': walletScreen, '/requests': requestsScreen, '/split': splitScreen, '/authorizations': holdsScreen };
const PUBLIC = { '/login': loginScreen, '/signup': signupScreen };
const TITLES = {
  '/': 'Wallet', '/requests': 'Requests', '/split': 'Split a bill', '/authorizations': 'Holds',
  '/login': 'Sign in', '/signup': 'Create an account',
};

let current = null; // { alive, dispose? } of the screen on show

export function navigate(path, { replace = false, notice = null } = {}) {
  if (replace) history.replaceState(null, '', path);
  else history.pushState(null, '', path);
  render(notice);
}

// Links inside the page move without a reload; modified clicks behave as browsers do.
function link(path, props, ...children) {
  return h('a', {
    href: path,
    ...props,
    onclick: (event) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      navigate(path);
    },
  }, ...children);
}

// The header on every screen: the product name; signed in, the navigation, who is signed in
// and the logout button; signed out, links to sign in and sign up.
function header(path) {
  const brand = link('/', { class: 'brand', 'aria-label': 'Pocketful, wallet' },
    h('span', { class: 'brand-mark', 'aria-hidden': 'true' }, 'P'), h('span', {}, 'Pocketful'));
  if (!session.token) {
    return h('header', { class: 'site-header' },
      h('div', { class: 'bar' }, brand,
        h('nav', { class: 'auth-links', 'aria-label': 'Account' },
          link('/login', { 'aria-current': path === '/login' ? 'page' : null }, 'Sign in'),
          link('/signup', { 'aria-current': path === '/signup' ? 'page' : null, class: 'button small' }, 'Create account'))));
  }
  const user = session.user;
  const who = h('div', { class: 'who' },
    h('span', { testid: 'current-user', class: 'user-name' }, user?.display_name ?? ''),
    h('span', { testid: 'current-handle', class: 'user-handle' }, user?.handle ?? ''));
  const logout = h('button', { type: 'button', testid: 'logout-button', class: 'button secondary small', onclick: logOut },
    icon('out'), 'Log out');
  return h('header', { class: 'site-header' },
    h('div', { class: 'bar' }, brand, h('div', { class: 'account' }, who, logout)),
    h('nav', { class: 'tabs', 'aria-label': 'Main' },
      NAV.map((item) => link(item.path, {
        testid: item.testid, class: 'tab', 'aria-current': item.path === path ? 'page' : null,
      }, icon(item.icon), h('span', {}, item.label)))));
}

// Called whenever a screen reads GET /me: the header shows the latest name and handle.
export function showUser(me) {
  session.remember(me);
  const name = document.querySelector('[data-testid="current-user"]');
  const handle = document.querySelector('[data-testid="current-handle"]');
  if (name && name.textContent !== me.display_name) name.textContent = me.display_name;
  if (handle && handle.textContent !== me.handle) handle.textContent = me.handle;
}

function logOut() {
  session.end();
  navigate('/login', { replace: false });
}

function notFoundScreen(main) {
  main.append(h('section', { class: 'card empty-state' },
    h('h1', {}, 'Page not found'),
    h('p', {}, 'There is nothing at this address.'),
    link(session.token ? '/' : '/login', { class: 'button' }, session.token ? 'Go to your wallet' : 'Sign in')));
  return { alive: true };
}

function render(notice = null) {
  if (current) {
    current.alive = false;
    current.dispose?.();
  }
  let path = location.pathname;
  let screen = PUBLIC[path] ?? SIGNED_IN[path] ?? notFoundScreen;
  if (SIGNED_IN[path] && !session.token) {
    path = '/login';
    history.replaceState(null, '', path);
    screen = loginScreen;
  }
  document.title = `${TITLES[path] ?? 'Page not found'} · Pocketful`;
  const main = h('main', { id: 'main', class: `main screen-${(path.slice(1) || 'wallet')}`, tabindex: '-1' });
  root.replaceChildren(
    h('a', { href: '#main', class: 'skip-link' }, 'Skip to content'),
    header(path),
    main,
  );
  const ctx = { alive: true, navigate, notice, showUser, link };
  current = ctx;
  const handle = screen(main, ctx);
  if (handle?.dispose) ctx.dispose = handle.dispose;
  // The header needs a name: read it when this browser does not know it yet.
  if (session.token && !session.user) {
    call('GET', '/me').then((outcome) => {
      if (outcome.kind === 'ok' && current === ctx) showUser(outcome.data);
    });
  }
}

// Only the session that was refused ends: a late 401 for an older token changes nothing.
whenSessionEnds((token) => {
  if (session.token !== token) return;
  session.end();
  navigate('/login', { replace: true, notice: 'Your session has ended. Please sign in again.' });
});

window.addEventListener('popstate', () => render());
render();
