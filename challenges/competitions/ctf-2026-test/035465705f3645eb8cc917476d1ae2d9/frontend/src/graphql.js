import { gql } from '@apollo/client';

// Список задач для главной страницы.
export const GET_TASKS = gql`
  query GetTasks {
    tasks {
      id
      title
      done
    }
  }
`;

// Профиль текущего пользователя (в шапке).
export const GET_ME = gql`
  query GetMe {
    me {
      id
      username
      email
    }
  }
`;

// TODO(sergey): удалить перед сборкой продакшена.
// Временный запрос для отладки профиля — раскрывает поле flag,
// которое мы пока держим в схеме. На проде его быть не должно.
//
// query DebugMe {
//   me {
//     id
//     username
//     email
//     flag
//   }
// }
//
// Не забыть убрать поле flag из backend/schema.js!