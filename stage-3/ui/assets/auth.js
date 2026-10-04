// Sign in and sign up (plan 3.14 "Session", D65): every refusal shows `auth-error`.

import { call, session } from './api.js';
import { fill, h, icon } from './dom.js';
import { field } from './kit.js';

const UNREACHABLE = 'We could not reach Pocketful. Check your connection and try again.';

function authForm(main, ctx, { title, intro, fields, submitTestid, submitLabel, endpoint, body, footer }) {
  const error = h('div', { class: 'status', 'aria-live': 'polite' });
  const button = h('button', { type: 'submit', testid: submitTestid, class: 'button wide' }, submitLabel);
  const form = h('form', { class: 'stack', novalidate: true }, fields.map((f) => f.el), error, button);
  let inFlight = false;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (inFlight) return;
    fill(error);
    inFlight = true;
    button.disabled = true;
    const outcome = await call('POST', endpoint, { body: body(), auth: false });
    inFlight = false;
    button.disabled = false;
    if (!ctx.alive) return;
    if (outcome.kind !== 'ok' || typeof outcome.data.token !== 'string') {
      const message = outcome.kind === 'refused' ? outcome.message : UNREACHABLE;
      fill(error, h('p', { testid: 'auth-error', class: 'message refused', role: 'alert' }, icon('alert'), h('span', {}, message)));
      return;
    }
    session.start(outcome.data.token);
    const me = await call('GET', '/me');
    if (me.kind === 'ok') session.remember(me.data);
    if (ctx.alive) ctx.navigate('/');
  });
  main.append(h('section', { class: 'card auth-card', 'aria-labelledby': 'auth-title' },
    h('h1', { id: 'auth-title' }, title),
    ctx.notice ? h('p', { class: 'message notice', role: 'status' }, icon('clock'), h('span', {}, ctx.notice)) : null,
    h('p', { class: 'muted' }, intro),
    form,
    footer));
  return { alive: true };
}

export function loginScreen(main, ctx) {
  const email = h('input', { type: 'email', testid: 'login-email', autocomplete: 'username', inputmode: 'email', spellcheck: 'false' });
  const password = h('input', { type: 'password', testid: 'login-password', autocomplete: 'current-password' });
  return authForm(main, ctx, {
    title: 'Sign in',
    intro: 'Welcome back. Sign in to see your wallet.',
    fields: [{ el: field('Email', email) }, { el: field('Password', password) }],
    submitTestid: 'login-submit',
    submitLabel: 'Sign in',
    endpoint: '/auth/login',
    body: () => ({ email: email.value.trim(), password: password.value }),
    footer: h('p', { class: 'muted switch' }, 'New to Pocketful? ', ctx.link('/signup', {}, 'Create an account')),
  });
}

export function signupScreen(main, ctx) {
  const email = h('input', { type: 'email', testid: 'signup-email', autocomplete: 'email', inputmode: 'email', spellcheck: 'false' });
  const password = h('input', { type: 'password', testid: 'signup-password', autocomplete: 'new-password' });
  const name = h('input', { type: 'text', testid: 'signup-display-name', autocomplete: 'name' });
  return authForm(main, ctx, {
    title: 'Create an account',
    intro: 'Your handle comes from your email address, so friends can find you.',
    fields: [
      { el: field('Email', email) },
      { el: field('Password', password, 'At least 8 characters.') },
      { el: field('Display name', name, 'What friends see, for example Ada Lovelace.') },
    ],
    submitTestid: 'signup-submit',
    submitLabel: 'Create account',
    endpoint: '/auth/signup',
    body: () => ({ email: email.value.trim(), password: password.value, display_name: name.value }),
    footer: h('p', { class: 'muted switch' }, 'Already have an account? ', ctx.link('/login', {}, 'Sign in')),
  });
}

