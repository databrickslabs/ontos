import Layout from '@theme/Layout';
import { JSX } from 'react';
import Button from '../components/Button';
import Link from '@docusaurus/Link';
import AnimatedOntosLogo from '../components/AnimatedOntosLogo';


import type {ReactNode} from 'react';
import clsx from 'clsx';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import HomepageFeatures from '@site/src/components/HomepageFeatures';
import Heading from '@theme/Heading';
import styles from './index.module.css';


/* function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={clsx('hero hero--primary', styles.heroBanner)}>
      <div className="container">
        <Heading as="h1" className="hero__title">
          {siteConfig.title}
        </Heading>
        <p className="hero__subtitle">{siteConfig.tagline}</p>
        <div className={styles.buttons}>
          <Link
            className="button button--secondary button--lg"
            to="/docs/intro">
            Docusaurus Tutorial - 5min ⏱️
          </Link>
        </div>
      </div>
    </header>
  );
} */

const Hero = () => {
  return (

  <header className={styles.heroBanner}>
    <div className="container flex flex-col items-center w-full">
      {/* Logo Section */}
      <div className={styles.imageOntos}>
        <AnimatedOntosLogo width={300} height={300} />
      </div>
      <h1 className={styles.centeredContent}>
        Ontos 
      </h1>
      <p className={styles.centeredContent}>
        A comprehensive data governance and management platform built for<a className={styles.spacedlink} href="https://www.databricks.com/product/unity-catalog">Databricks Unity Catalog.</a>
      </p>
      {/* Call to Action Buttons */}
      <div className={styles.centeredContent}>
        <div className={styles.buttonSpacing}>
        <Button
          variant="secondary"
          outline={true}
          link="/docs/introduction/motivation"
          size="large"
          label={"Motivation"}
          className="w-full md:w-auto"
        />
        </div>
        <div className={styles.buttonSpacing}>
        <Button
          variant="secondary"
          outline={true}
          link="/docs/category/getting-started"
          size="large"
          label={"Getting Started"}
          className="w-full md:w-auto"
        />
        </div>
        <div className={styles.buttonSpacing}>
        <Button
          variant="secondary"
          outline={true}
          link="/docs/faq"
          size="large"
          label="FAQ"
          className="w-full md:w-auto"
        />
        </div>
      </div>
    </div>
  </header>
  );
};

export default function Home(): JSX.Element {
  return (
    <Layout>
      <main>
        <div className="container padding-top--md padding-bottom--lg padding-horiz--none">
          <Hero />
        </div>
      </main>
    </Layout>
  );
}


/* export default function Home(): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={`Hello from ${siteConfig.title}`}
      description="Description will go into a meta tag in <head />">
      <HomepageHeader />
      <main>
        <HomepageFeatures />
      </main>
    </Layout>
  );

} */
