/**
 * GraphQL-схема таск-трекера.
 *
 * TODO(sergey): убрать поле `flag` из типа User перед публикацией
 * в продакшен. Пока оставил — удобно смотреть в GraphiQL.
 */
const { gql } = require('graphql-tag');

const FLAG = process.env.FLAG || 'flag{graphql_intr0sp3ct10n_1s_n0t_s3cur3}';

const typeDefs = gql`
  type User {
    id: ID!
    username: String!
    email: String!
    flag: String
  }

  type Task {
    id: ID!
    title: String!
    done: Boolean!
    owner: User!
  }

  type Query {
    me: User
    tasks: [Task!]!
    task(id: ID!): Task
  }
`;

const OPERATOR = {
  id: '1',
  username: 'operator',
  email: 'operator@ordo.local',
};

const TASKS = [
  { id: '1', title: 'Прочитать документацию по безопасности', done: true },
  { id: '2', title: 'Настроить CI/CD для нового сервиса',    done: false },
  { id: '3', title: 'Отозвать старые API-ключи',             done: false },
  { id: '4', title: 'Обновить схему GraphQL',                done: false },
  { id: '5', title: 'Проверить audit log',                   done: true },
];

const resolvers = {
  Query: {
    me: () => OPERATOR,
    tasks: () => TASKS.map(t => ({ ...t, owner: OPERATOR })),
    task: (_, { id }) => {
      const t = TASKS.find(x => x.id === id);
      if (!t) return null;
      return { ...t, owner: OPERATOR };
    },
  },
  User: {
    flag: () => FLAG,
  },
};

module.exports = { typeDefs, resolvers };